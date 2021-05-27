#!/usr/bin/python3

import pickle
import sys
import numpy as np

#
# Loads and then describes a pedestal
#

aPedestal = pickle.load(open(sys.argv[1], "rb"))

for chan in aPedestal.mean:

    print("# Channel: %d" % chan)

    n = 0

    #fmt = lambda x: x if not x is None else float('nan')
    
    for mean, var, count in zip(aPedestal.mean[chan], aPedestal.rms[chan], aPedestal.counts[chan]):
        mean12 = (np.int64(mean) & 0xFFFF) >> 4
        var12 = (np.int64(var) & 0xFFFF) >> 4 if not np.isnan(var) else 0
        
        print("%d %d %d %d %d" % (n, np.int64(mean), np.int64(var), chan, count))
        n += 1

    # Break on channel
    print("")
