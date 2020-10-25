#!/usr/bin/python3
import numpy as np
import sys
import time

import packette_stream as packette
from packette_pedestal import pedestal

import A2x_common

# Set up a new tool, with arguments common to the event digestion
# subsystem.  All tools will share the same baseline syntax and semantics.
parser = A2x_common.create("Measure per capacitor gain slopes between two given voltages")

# Add some specific options for this tool
# These default values calibrate pretty well
parser.add_argument('low', metavar='LOW', type=float, default=0.7, help='Use this as the low voltage sample')
parser.add_argument('high', metavar='HIGH', type=float, default=1, help='Use this value as the high voltage sample')
parser.add_argument('datafile', metavar='DATA',type=str, help='Read board output events in real-time from this run')

# Handle common configuration due to the common arguments
ifc, args = A2x_common.connect(parser)

# Open up the events
events = packette_stream.packetteRun(args.datafile)

# Tell the user what we are dusering
print("# CMOFS: %f\n# TCAL_low: %f\n# TCAL_high: %f\n# ROFS: %f" % (args.cmofs, args.low, args.high, args.rofs))

event_boundaries = []

for voltage in (args.low, args.high):
    # Set the low value
    ifc.DacSetVout(lappdTool.DAC_TCAL_N1, voltage)
    ifc.DacSetVout(lappdTool.DAC_TCAL_N2, voltage)

    # Give some output
    print("Receiving data for TCAL_N = %f" % voltage, file=sys.stderr)

    k = args.N
    # Take N samples at both low and high
    while k > 0:
        # Wait for it to settle
        time.sleep(args.i)

        # Software trigger
        ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

        # Add some info and stash it
        evt.voltage = voltage
        evts.append(evt)
        k -= 1

    # Refresh the file index
    events.updateIndex()

    # Remember how many events we got, since these events correspond
    # to these values in the curve
    event_count[voltage] = len(events)
    
# For the analysis, we need SCA view
events.setSCAView(True)

print(event_count)










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

    # Open the packette run
    events = packette.packetteRun(fname)

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
                sumsquares[chan][i] = math.sqrt(sumsquares[chan][i]/counts[chan][i] - sums[chan][i]**2)
            else:
                print("WARNING: received zero counts for channel %d, capacitor %d" % (chan, i))

    # Write out a binary timing file
    import pickle
    pickle.dump(pedestal(sums, sumsquares, counts), open("boardid.pedestal", 'wb'))
