#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
:py:mod:`pbs.py` - PBS cluster routines
---------------------------------------

'''

from __future__ import division, print_function, absolute_import, unicode_literals
from .aux import *
from .k2 import GetData
from ...config import EVEREST_SRC, EVEREST_DAT, EVEREST_DEV
from ...utils import ExceptionHook, FunctionWrapper
from ...pool import Pool
import os, sys, subprocess
import pickle
import logging
log = logging.getLogger(__name__)

# Constants
RED =    '\033[0;31m'
GREEN =  '\033[0;32m'
BLACK =  '\033[0m'
BLUE =   '\033[0;34m'

def Download(campaign = 0, queue = 'build', email = None, walltime = 8, **kwargs):
  '''
  Submits a cluster job to the build queue to download all TPFs for a given
  campaign.
  
  :param int campaign: The `K2` campaign to run
  :param str queue: The name of the queue to submit to. Default `build`
  :param str email: The email to send job status notifications to. Default `None`
  :param int walltime: The number of hours to request. Default `8`
  
  '''
  
  # Figure out the subcampaign
  if type(campaign) is int:
    subcampaign = -1
  elif type(campaign) is float:
    x, y = divmod(campaign, 1)
    campaign = int(x)
    subcampaign = round(y * 10)
  # Submit the cluster job      
  pbsfile = os.path.join(EVEREST_SRC, 'missions', 'k2', 'download.pbs')
  str_w = 'walltime=%d:00:00' % walltime
  str_v = 'EVEREST_DAT=%s,CAMPAIGN=%d,SUBCAMPAIGN=%d' % (EVEREST_DAT, campaign, subcampaign)
  if subcampaign == -1:
    str_name = 'download_c%02d' % campaign
  else:
    str_name = 'download_c%02d.%d' % (campaign, subcampaign)
  str_out = os.path.join(EVEREST_DAT, 'k2', str_name + '.log')
  qsub_args = ['qsub', pbsfile, 
               '-q', queue,
               '-v', str_v, 
               '-o', str_out,
               '-j', 'oe', 
               '-N', str_name,
               '-l', str_w]
  if email is not None: qsub_args.append(['-M', email, '-m', 'ae'])
  # Now we submit the job
  print("Submitting the job...")
  subprocess.call(qsub_args)

def _Download(campaign, subcampaign):
  '''
  Download all stars from a given campaign. This is
  called from ``missions/k2/download.pbs``
  
  '''

  # Are we doing a subcampaign?
  if subcampaign != -1:
    campaign = campaign + 0.1 * subcampaign
  # Get all star IDs for this campaign
  stars = [s[0] for s in GetK2Campaign(campaign)]
  nstars = len(stars)
  # Download the TPF data for each one
  for i, EPIC in enumerate(stars):
    print("Downloading data for EPIC %d (%d/%d)..." % (EPIC, i + 1, nstars))
    if not os.path.exists(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % int(campaign), 
                         ('%09d' % EPIC)[:4] + '00000', ('%09d' % EPIC)[4:],
                         'data.npz')):
      try:
        GetData(EPIC, download_only = True)
      except KeyboardInterrupt:
        sys.exit()
      except:
        # Some targets could be corrupted...
        print("ERROR downloading EPIC %d." % EPIC)
        continue

def Run(campaign = 0, nodes = 5, ppn = 12, walltime = 100, 
        mpn = None, email = None, queue = None, **kwargs):
  '''
  Submits a cluster job to compute and plot data for all targets in a given campaign.
  
  :param campaign: The K2 campaign number. If this is an :py:class:`int`, returns \
                   all targets in that campaign. If a :py:class:`float` in the form \
                   `X.Y`, runs the `Y^th` decile of campaign `X`.
  :param str queue: The queue to submit to. Default `None` (default queue)
  :param str email: The email to send job status notifications to. Default `None`
  :param int walltime: The number of hours to request. Default `100`
  :param int nodes: The number of nodes to request. Default `5`
  :param int ppn: The number of processors per node to request. Default `12`
  :param int mpn: Memory per node in gb to request. Default no setting.
    
  '''
  
  # Figure out the subcampaign
  if type(campaign) is int:
    subcampaign = -1
  elif type(campaign) is float:
    x, y = divmod(campaign, 1)
    campaign = int(x)
    subcampaign = round(y * 10) 
  
  # DEV hack: limit backfill jobs to 4 hours
  if EVEREST_DEV and (queue == 'bf'):
    walltime = min(4, walltime)
  
  # Convert kwargs to string. This is really hacky. Pickle creates an array
  # of bytes, which we must convert into a regular string to pass to the pbs
  # script and then back into python. Decoding the bytes isn't enough, since
  # we have pesky escaped characters such as newlines that don't behave well
  # when passing this string around. My braindead hack is to replace newlines
  # with '%%%', then undo the replacement when reading the kwargs. This works
  # for most cases, but sometimes pickle creates a byte array that can't be
  # decoded into utf-8 -- this happens when trying to pass numpy arrays around,
  # for instance. This needs to be fixed in the future, but for now we'll 
  # restrict the kwargs to be ints, floats, lists, and strings.
  try:
    strkwargs = pickle.dumps(kwargs, 0).decode('utf-8').replace('\n', '%%%')
  except UnicodeDecodeError:
    raise ValueError('Unable to pickle `kwargs`. Currently the `kwargs` values may only be' +
                     '`int`s, `float`s, `string`s, `bool`s, or lists of these.')
  
  # Submit the cluster job      
  pbsfile = os.path.join(EVEREST_SRC, 'missions', 'k2', 'run.pbs')
  if mpn is not None:
    str_n = 'nodes=%d:ppn=%d,feature=%dcore,mem=%dgb' % (nodes, ppn, ppn, mpn * nodes)
  else:
    str_n = 'nodes=%d:ppn=%d,feature=%dcore' % (nodes, ppn, ppn)
  str_w = 'walltime=%d:00:00' % walltime
  str_v = "EVEREST_DAT=%s,NODES=%d,CAMPAIGN=%d,SUBCAMPAIGN=%d,STRKWARGS='%s'" % (EVEREST_DAT, 
          nodes, campaign, subcampaign, strkwargs)
  if subcampaign == -1:
    str_name = 'c%02d' % campaign
  else:
    str_name = 'c%02d.%d' % (campaign, subcampaign)
  str_out = os.path.join(EVEREST_DAT, 'k2', str_name + '.log')
  qsub_args = ['qsub', pbsfile, 
               '-v', str_v, 
               '-o', str_out,
               '-j', 'oe', 
               '-N', str_name,
               '-l', str_n,
               '-l', str_w]
  if email is not None: 
    qsub_args.append(['-M', email, '-m', 'ae'])
  if queue is not None:
    qsub_args += ['-q', queue]          
  
  # Now we submit the job
  print("Submitting the job...")
  subprocess.call(qsub_args)

def _Run(campaign, subcampaign, strkwargs):
  '''
  The actual function that runs a given campaign; this must
  be called from ``missions/k2/run.pbs``.
  
  '''
  
  # Get kwargs from string
  kwargs = pickle.loads(strkwargs.replace('%%%', '\n').encode('utf-8'))
  
  # Model wrapper
  m = FunctionWrapper(EverestModel, **kwargs)
  
  # Set up our custom exception handler
  sys.excepthook = ExceptionHook
  # Initialize our multiprocessing pool
  with Pool() as pool:
    # Are we doing a subcampaign?
    if subcampaign != -1:
      campaign = campaign + 0.1 * subcampaign
    # Get all the stars
    stars = GetK2Campaign(campaign, epics_only = True)
    # Run
    pool.map(m, stars)

def Status(campaign = range(18), model = 'nPLD', purge = False, **kwargs):
  '''
  Shows the progress of the de-trending runs for the specified campaign(s).

  '''
  
  if not hasattr(campaign, '__len__'):
    if type(campaign) is int:
      # Return the subcampaigns
      all_stars = [s for s in GetK2Campaign(campaign, split = True, epics_only = True)]
      campaign = [campaign + 0.1 * n for n in range(10)]
    else:
      all_stars = [[s for s in GetK2Campaign(campaign, epics_only = True)]]
      campaign = [campaign]
  else:
    all_stars = [[s for s in GetK2Campaign(c, epics_only = True)] for c in campaign]
  print("CAMP      TOTAL      DOWNLOADED    PROCESSED    ERRORS")
  print("----      -----      ----------    ---------    ------")
  for c, stars in zip(campaign, all_stars):
    if len(stars) == 0:
      continue
    down = 0
    proc = 0
    err = 0
    bad = []
    remain = []
    total = len(stars)
    if os.path.exists(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c)):
      path = os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c)
      for folder in os.listdir(path):
        for subfolder in os.listdir(os.path.join(path, folder)):
          if os.path.exists(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c, folder, subfolder, 'data.npz')):
            if int(folder[:4] + subfolder) in stars:
              down += 1
              if os.path.exists(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c, folder, subfolder, model + '.npz')):
                proc += 1
              elif os.path.exists(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c, folder, subfolder, model + '.err')):
                err += 1
                bad.append(folder[:4] + subfolder)
                if purge:
                  os.remove(os.path.join(EVEREST_DAT, 'k2', 'c%02d' % c, folder, subfolder, model + '.err'))
              else:
                remain.append(folder[:4] + subfolder)
    if proc == total:
      cc = ct = cd = cp = ce = GREEN
    else:
      cc = BLACK
      ct = BLACK
      cd = BLACK if down < total else BLUE
      cp = BLACK if proc < down or proc == 0 else BLUE
      ce = RED if err > 0 else BLACK
    if type(c) is int:
      print("%s{:>4d}   \033[0m%s{:>8d}\033[0m%s{:>16d}\033[0m%s{:>13d}\033[0m%s{:>10d}\033[0m".format(c, total, down, proc, err)
            % (cc, ct, cd, cp, ce))
    else:
      print("%s{:>4.1f}   \033[0m%s{:>8d}\033[0m%s{:>16d}\033[0m%s{:>13d}\033[0m%s{:>10d}\033[0m".format(c, total, down, proc, err)
            % (cc, ct, cd, cp, ce))
    if len(remain) <= 25 and len(remain) > 0 and len(campaign) == 1:
      remain.extend(["         "] * (4 - (len(remain) % 4)))
      print()
      for A, B, C, D in zip(remain[::4],remain[1::4],remain[2::4],remain[3::4]):
        if A == remain[0]:
          print("REMAIN:  %s   %s   %s   %s" % (A, B, C, D))
          print()
        else:
          print("         %s   %s   %s   %s" % (A, B, C, D))
          print()
    if len(bad) and len(campaign) == 1:
      bad.extend(["         "] * (4 - (len(bad) % 4)))
      print()
      for A, B, C, D in zip(bad[::4],bad[1::4],bad[2::4],bad[3::4]):
        if A == bad[0]:
          print("ERRORS:  %s   %s   %s   %s" % (A, B, C, D))
          print()
        else:
          print("         %s   %s   %s   %s" % (A, B, C, D))
          print()

def EverestModel(ID, model = 'nPLD', **kwargs):
  '''
  
  '''
  
  from ... import model as everest_model
  getattr(everest_model, model)(ID, **kwargs)
  return True