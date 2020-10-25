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
events = packette.packetteRun(args.datafile)

# Tell the user what we are dusering
print("# CMOFS: %f\n# TCAL_low: %f\n# TCAL_high: %f\n# ROFS: %f" % (args.cmofs, args.low, args.high, args.rofs))

event_count = {}

for voltage in (args.low, args.high):
    # Set the low value
    ifc.DacSetVout(ifc.DACOUTS['TCAL_N1'], voltage)
    ifc.DacSetVout(ifc.DACOUTS['TCAL_N2'], voltage)

    # Give some output
    print("Receiving data for TCAL_N = %f" % voltage, file=sys.stderr)

    k = args.N
    # Take N samples at both low and high
    while k > 0:
        # Wait for it to settle
        time.sleep(args.i)

        # Software trigger
        ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

        k -= 1
        
    # Refresh the file index
    events.updateIndex()

    # Remember how many events we got, since these events correspond
    # to these values in the curve
    event_count[voltage] = len(events)
    
# For the analysis, we need SCA view
events.setSCAView(True)

print(event_count)

# The slope denominator
run = args.high - args.low

# Iterate over channels, because we want response curves per channel
firstevent = iter(events).__next__()

chans = firstevent.channels.keys()

caps_low = {}
caps_high = {}
slopes = {}

from scipy.stats import describe
import math

for chan in chans:
    
    # Now prepare to store the average gains
    caps_low[chan] = [[] for x in range(1024)]
    caps_high[chan] = [[] for x in range(1024)]
    slopes[chan] = [[] for x in range(1024)]
    
    # Filter out any masked capacitors
    for n,evt in enumerate(events):

        # In case the order is wonky for some reason?
        if n < event_count[args.low]:
            caps = caps_low[chan]
        else:
            caps = caps_high[chan]

        # Save this data point
        for cap in range(1024):
            if evt.channels[chan][cap] is packette.NOT_DATA:
                continue
            
            # Record it
            caps[cap].append(evt.channels[chan][cap])

    # In case events got lost, we need to truncate to the shortest list
    samples = min(len(caps_high[chan][cap]), len(caps_low[chan][cap]))
    caps_high[chan][cap][:samples]
    caps_low[chan][cap][:samples]
    
    # Now caps are nicely sorted, take averages and std deviations
    for cap in range(1024):

        # Replace the lists with tuples containing the statistical dirt
        caps_high[chan][cap] = describe(caps_high[chan][cap])
        caps_low[chan][cap] = describe(caps_low[chan][cap])

        # Now make the slopes and propogated RMSs
        varhigh = caps_high[chan][cap].variance
        varlow = caps_low[chan][cap].variance

        ampl_variance = math.sqrt(caps_high[chan][cap].variance + caps_low[chan][cap].variance)/(run*math.sqrt(samples))
        recip_k = run/(caps_high[chan][cap].mean - caps_low[chan][cap].mean)
        
        # We want recriprocal slopes
        slopes[chan][cap] = ( recip_k, recip_k**2 * ampl_variance)

# Output a correction file
import pickle
pickle.dump(slopes, open("%s.gains" % events.board_id.hex(), "wb"))
    
# Now output the results
for channel, results in slopes.items():
    print("# BEGIN CHANNEL %d" % channel)
    for cap, value in enumerate(results):
        print("%d %e %e %d" % (cap, value[0], value[1], channel))
    print("# END OF CHANNEL %d\n" % channel)
