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
        sums[chan] = np.zeros([1024], dtype=np.float)
        sumsquares[chan] = np.zeros([1024], dtype=np.float)
        counts[chan] = np.zeros([1024], dtype=np.int32)
    
    for event in events:
        for chan in chans:

            # Generate the mask fast
            flags = event.channels[chan] & 0xF

            # Lets try to be clever here
            # This is liquid fast!
            valid = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

            # Zero out masked flagged data since we don't want to use it
            stripped = np.array(event.channels[chan] * valid, dtype=np.int64)

            # Use numpy vectorization
            # (Because numpy computes the RHS first, honouring type, and then assigns
            #  the np.int16's that would normally be here instead of int64's OVERFLOW)
            sums[chan] += stripped
            sumsquares[chan] += stripped*stripped

            # Accumulate where we *didn't* knockout
            counts[chan] += valid

    # We've processed all we could, ship it back
    return (sums, sumsquares, counts, events.board_id)

#
# Entry point for the calibrator
#
if __name__ == '__main__':

    # Use Pool, slicker.
    with multiprocessing.Pool(4) as p:
         print("pedestal_calibration.py: spawning a worker process per file ...")
         results = p.map(pedestalAccumulator, sys.argv[1:])

    print("pedestal_calibration.py: ... workers complete.")

    for psums, psumsquares, pcounts, board_id in results:        
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

    # For clarity, for explicit casting, and weird issues with assigmnet during computation?
    avgs = {}
    stdevs = {}
    for chan in sums.keys():
        avgs[chan] = np.empty([1024], dtype=np.int16)
        stdevs[chan] = np.empty([1024])
        
    # Compute averages and the average squares
    # We have to do these explicitly, but this takes constant time, instead of scaling like number of events
    for chan in sums.keys():

        # Use numpy to vectorize this
        avgs[chan] = np.floor(sums[chan]/counts[chan])

        # Also try here
        stdevs[chan] = np.sqrt(sumsquares[chan]/counts[chan] - avgs[chan]**2)

    # Write out a binary timing file
    import pickle
    pickle.dump(pedestal(sums, sumsquares, counts), open("%s.pedestal" % board_id.hex(), 'wb'))
