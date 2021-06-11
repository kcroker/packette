#!/usr/bin/python3
import sys
import numpy as np
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import A2x_common
import packette_stream as packette
from collections import deque

# Make a new tool
# parser = A2x_common.create('Barebones oscilloscope for packette protocol Ultralytics A2x series boards')
# ifc, args = A2x_common.connect(parser)

# Set it up to read streamed events
events = packette.packetteRun((sys.argv[1], 1338), streaming=True)

# Matplotlib stuff
plt.style.use('dark_background')

# Set up figures for oscilliscope and channel hit rate heat map
fig, ax = plt.subplots(2,1)

scope = ax[0,0]
hitrate = ax[1,0]

xmax = 1040
xmin = -10

# Shift y-scale to milivolts
gain = 1000./(16*2048)

# Doesnt work with dictionaries?
lines = []

# So we go through all possible channels and make lines (for each channel), so they are always present
# Then we will change the data backing each particular line as things come in.
for chan in range(64):
    line = scope.plot(np.linspace(xmin, xmax, 10), [0]*10, linewidth=1, linestyle=('solid' if chan < 31 else 'dashed'))[0]
    line.set_label('Channel %d' % chan)
    lines.append(line)

print("packette_scope.py: Initial lines established", file=sys.stderr)

# We definitely have to hold things fixed, or else the scale will change with every pulse...
scope.set_ylim(-50, 50)
scope.set_xlim(xmin, xmax)
scope.set_ylabel("Millivolts")
scope.set_xlabel("Some unit of time between capacitors")
scope.legend()
zeros = np.zeros((1024), dtype=np.int16)
dom = range(1024)

# Title objects
scope_title = scope.title("Waiting for data...")
hitrate_title = hitrate.title("Channel hitrates over past 100 events (relative)")

# Channel hit list deques
temp_accumulators = []

# For use with imshow:
#  (0,27) are the 28 strips
#  (28) is always black
#  (29-32) are the calibration indicators

temps = np.zeros((2,28+1+4), dtype=np.uint8)

# Get the artist object
heat = hitrate.imshow(temps)

# Increments the right spot in the imshow matrices
# given the channel number
def temptag(chan, incr):

    # see if its a strip
    if chan in A2x_common.exploded_inverse_strips:
        # Get the strip
        strip = A2x_common.exploded_inverse_strips[chan]

        # Get the top or bottom
        if chan < 32:
            # Top
            temps[(0, strip-1)] += incr
        else:
            # Bottom
            temps[(1, strip-1)] += incr
    else:
        # Its a calibration line
        cal = A2x_common.inverse_calibrations[chan]

        if chan < 32:
            temps[(0, 29 + cal-1)] += incr
        else:
            temps[(1, 29 + cal-1)] += incr
    
for i in range(64):
    temp_accumulators.append(deque())

def animate(i):

    # Get one off the deque
    try:
        event = events.popEvent()

        # Print it (looks cool)
        print(event)

        # Keep track of the heatmap
        for chan in range(64):
            if chan in event.channels.keys():
                temp_accumulators[chan].append(1)
                temptag(chan, 1)
            else:
                temp_accumulators[chan].append(0)

            # Pop if necessary
            if len(temp_accumulators[chan]) > 255:
                temptag(chan, -temp_accumulators[chan].popleft())
            
        # Set the title 
        scope_title.set_text("Board %s, Event %d" % (event.prettyid(), event.event_num))
        
        # Update the channels
        for chan,line in enumerate(lines):
            if chan in event.channels.keys():
                line.set_data(dom, gain * event.channels[chan])
            else:
                line.set_data(dom, zeros)

        # Update the heatmap
        heat.set_data(temps)
        
    except IndexError as e:
        # Empty queue
        pass
    
    # Return all things to be updated
    return (*lines, scope_title, heat)

# Go as fast as possible, what could go wrong?
ani = animation.FuncAnimation(fig, animate, interval=0, blit=True, save_count=10)
plt.show()

