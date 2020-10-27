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

    # Iterate through it
    for event in events:
            
        # If this is the first event, do some initialization on our end
        if chans is None:
            chans = event.channels.keys()
            
            for chan in chans:
                # Initialize the pairs list
                sums[chan] = [0 for x in range(1024)]
                sumsquares[chan] = [0 for x in range(1024)]
                rmss[chan] = [0.0 for x in range(1024)]

                # Initialize the count of tabulated samples
                counts[chan] = [0 for i in range(1024)]

        # Process it right here.
        for chan in event.channels.keys():
            for i in range(1024):

                # If its not data, skip it
                if event.channels[chan][i] == packette.NOT_DATA:
                    continue

                sums[chan][i] += event.channels[chan][i]
                sumsquares[chan][i] += event.channels[chan][i]**2
                counts[chan][i] += 1
                    
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
                for i in range(1024):
                    sums[chan][i] += psums[chan][i]
                    sumsquares[chan][i] += psumsquares[chan][i]
                    counts[chan][i] += pcounts[chan][i]

    # Compute averages and the average squares
    import math
    for chan in sums.keys():
        for i in range(1024):
            # Make sure its an integer (so we can do fast integer subtraction when pedestalling raw ADC counts)
            if counts[chan][i] > 0:
                sums[chan][i] = round(sums[chan][i]/counts[chan][i])
                try:
                    sumsquares[chan][i] = math.sqrt(sumsquares[chan][i]/counts[chan][i] - sums[chan][i]**2)
                except ValueError as e:
                    print("Fuck you")
                    pass
            else:
                print("WARNING: received zero counts for channel %d, capacitor %d" % (chan, i))

    # Write out a binary timing file
    import pickle
    pickle.dump(pedestal(sums, sumsquares, counts), open("boardid.pedestal", 'wb'))
