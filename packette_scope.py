#!/usr/bin/python3
import sys
import numpy as np
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import A2x_common
import packette_stream as packette

# Make a new tool
# parser = A2x_common.create('Barebones oscilloscope for packette protocol Ultralytics A2x series boards')
# ifc, args = A2x_common.connect(parser)

# Set it up to read streamed events
events = packette.packetteRun((sys.argv[1], 1338), streaming=True)

fig = plt.figure()
ax = plt.axes()

xmax = 1040
xmin = -10

# Shift y-scale to milivolts
gain = 1000./(16*2048)

# Doesnt work with dictionaries?
lines = []

# So we go through all possible channels and make lines (for each channel), so they are always present
# Then we will change the data backing each particular line as things come in.
for chan in range(64):
    line = ax.plot(np.linspace(xmin, xmax, 10), [0]*10, linewidth=1, linestyle=('solid' if chan < 31 else 'dashed'))[0]
    line.set_label('Channel %d' % chan)
    lines.append(line)

print("packette_scope.py: Initial lines established", file=sys.stderr)

# We definitely have to hold things fixed, or else the scale will change with every pulse...
ax.set_ylim(-50, 50)
ax.set_xlim(xmin, xmax)
ax.set_ylabel("Millivolts")
ax.set_xlabel("Some unit of time between capacitors")
ax.legend()
zeros = np.zeros((1024), dtype=np.int16)
dom = range(1024)

# Title object
title = plt.title("Waiting for data...")

def animate(i):

    # Get one off the deque
    try:
        event = events.popEvent()

        print(event)

        title.set_text("Board %s, Event %d" % (event.prettyid(), event.event_num))
        for chan,line in enumerate(lines):
            if chan in event.channels.keys():
                line.set_data(dom, gain * event.channels[chan])
            else:
                line.set_data(dom, zeros)
                    
    except IndexError as e:
        # Empty queue
        pass
    
    # Returning a global, what could go wrong?
    return lines#, title)#,

ani = animation.FuncAnimation(fig, animate, interval=10, blit=True, save_count=10)
plt.show()

