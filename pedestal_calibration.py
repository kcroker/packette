#!/usr/bin/python3
import numpy as np
import sys
import time

# We're gonna really streamline this
import multiprocessing

import packette_stream as packette
from packette_pedestal import pedestal

#
# Each process will have its own copy of these variables.
#
sums = {}
sumsquares = {}
rmss = {}
counts = {}

chans = None

#
# In this way, huge lists of event data never need to be shippped via IPC
# The callback must be defined above its use in the intake() as a hook, because Python.
#
def pedestalAccumulator(fname):

    global chans

    # Open the packette run (with view set to capacitor ordering)
    events = packette.packetteRun(fname, SCAView=True)

    # Get an event
    firstevent = iter(events).__next__()

    # Pedestal accumulation assumes that the channel mask NEVER CHANGES!!!
    chans = firstevent.channels.keys()

    # Initialize accounting
    for chan in firstevent.channels.keys():
        sums[chan] = np.zeros([1024])
        sumsquares[chan] = np.zeros([1024])
        rmss[chan] = np.zeros([1024])
        counts[chan] = np.zeros([1024])
    
    for event in events:
        for chan in chans:

            # Strip out flags
            stripped = event.channels[chan] & ~0xF
            flags = event.channels[chan] & 0xF
            
            # Use numpy vectorization
            sums[chan] += stripped
            sumsquares[chan] += stripped*stripped

            # Lets try to be clever here
            # This is liquid fast!
            counts[chan] += 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

    # We've processed all we could, ship it back
    return (sums, sumsquares, counts)

#
# Entry point for the calibrator
#
if __name__ == '__main__':

    # Use Pool, slicker.
    with multiprocessing.Pool(4) as p:
         print("pedestal_calibration.py: spawning a worker process per file ...")
         results = p.map(pedestalAccumulator, sys.argv[1:])

    print("pedestal_calibration.py: ... workers complete.")

    for psums, psumsquares, pcounts in results:        
        # Accumulate into the first responder
        if len(sums.keys()) == 0:
            sums = psums
            sumsquares = psumsquares
            counts = pcounts
        else:
            for chan in sums.keys():
                sums[chan] += psums[chan]
                sumsquares[chan] += psumsquares[chan]
                counts[chan] += pcounts[chan]

    # Compute averages and the average squares
    # We have to do these explicitly, but this takes constant time, instead of scaling like number of events
    for chan in sums.keys():

        # Use numpy to vectorize this
        sums[chan] = np.round(sums[chan]/counts[chan])

        # Also try here
        sumsquares[chan] = np.sqrt(sumsquares[chan]/counts[chan] - sums[chan]**2)

    # Write out a binary timing file
    import pickle
    pickle.dump(pedestal(sums, sumsquares, counts), open("boardid.pedestal", 'wb'))
