#!/usr/bin/python3

import pickle
import sys

#
# Loads and then describes a pedestal
#

aPedestal = pickle.load(open(sys.argv[1], "rb"))

for chan in aPedestal.mean:

    print("# Channel: %d" % chan)

    n = 0

    #fmt = lambda x: x if not x is None else float('nan')
    
    for mean, var, count in zip(aPedestal.mean[chan], aPedestal.rms[chan], aPedestal.counts[chan]):
        print("%d %e %e %d %d" % (n, mean, var, chan, count))
        n += 1

    # Break on channel
    print("")
