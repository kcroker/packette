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
events = packette.packetteRun((sys.argv[1], 5683), streaming=True)

# Matplotlib stuff
plt.style.use('dark_background')

# Set up figures for oscilliscope and channel hit rate heat map
fig, ax = plt.subplots(2,1)
fig.subplots_adjust(hspace=0,wspace=0)

scope = ax[0]
hitmap = ax[1]

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
scope.set_ylim(-30, 60)
scope.set_xlim(xmin, xmax)
scope.set_ylabel("Millivolts")
scope.set_xlabel("Some unit of time between capacitors")
scope.grid('on', linestyle='--', linewidth=1, color='gray')

zeros = np.zeros((1024), dtype=np.int16)
dom = np.linspace(0, 1023, 1024) 

# Title objects
scope_title = scope.set_title("Waiting for data...")

# Strip labels on channels
bottom_labels = [(x, A2x_common.strips[x+1][1]) for x in range(28)]
top_labels = [(x, A2x_common.strips[x+1][0]) for x in range(28)]

# Calibration labels
bottom_labels += [(x+29, A2x_common.calibrations[4+x+1]) for x in range(4)] 
top_labels += [(x+29, A2x_common.calibrations[x+1]) for x in range(4)]

hitmap.set_xticks([x[0] for x in bottom_labels])
hitmap.set_xticklabels([x[1] for x in bottom_labels])

# Cheat with minor ticks (all me buddy!)
hitmap.tick_params(axis='x', which='minor', direction='out', bottom=False, labelbottom=False, top=True, labeltop=True)
hitmap.set_xticks([x[0] for x in top_labels], minor=True)
hitmap.set_xticklabels([x[1] for x in top_labels], minor=True)

hitmap.set_yticks([0,1])
hitmap.set_yticklabels(['Top row (SFP cage)', 'Bottom row'])


# Hide the ugly border
hitmap.spines['top'].set_visible(False)
hitmap.spines['right'].set_visible(False)
hitmap.spines['bottom'].set_visible(False)
hitmap.spines['left'].set_visible(False)

#hitmap.set_xticks([x[0] for x in bottom_labels])
#hitmap.set_xticklabels([x[1] for x in bottom_labels])

hitmap.yaxis.set_label_position("right")
hitmap.set_ylabel("Calibration")

# Channel hit list deques
temp_accumulators = []

# For use with imshow:
#  (0,27) are the 28 strips
#  (28) is always black
#  (29-32) are the calibration indicators

temps = np.zeros((2,28+1+4), dtype=np.uint8)

# Get the artist object
heat = hitmap.imshow(temps, vmin=0, vmax=32)

# Mask out the separation between strips and calibration channels
import matplotlib.patches as patches

rect = patches.Rectangle((27.5, -0.5), 1, 2, linewidth=0, edgecolor='black', facecolor='black', zorder=3, fill=True)
hitmap.add_patch(rect)

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
            temps[(1, 29 + (cal-4)-1)] += incr
    
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
            if len(temp_accumulators[chan]) > 32:
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
        heat.set_array(temps)
        
    except IndexError as e:
        import traceback
        print(e)
        traceback.print_tb(e.__traceback__)
        # Empty queue
        pass
    
    # Return all things to be updated
    return (*lines, scope_title, heat, rect)

# Go as fast as possible, what could go wrong?
ani = animation.FuncAnimation(fig, animate, interval=0, blit=True, save_count=10)
plt.show()

