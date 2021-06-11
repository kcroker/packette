#!/usr/bin/python3
import sys
import numpy as np
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import A2x_common

# Make a new tool
parser = A2x_common.create('Barebones oscilloscope for packette protocol Ultralytics A2x series boards')
ifc, args = A2x_common.connect(parser)

# Set it up to read streamed events
events = packette.packetteRun(args.board, streaming=True)

fig = plt.figure()
ax = plt.axes()

xmax = 1040
xmin = -10

# Shift y-scale to milivolts
gain = 1./(16*2048)

# Doesnt work with dictionaries?
lines = []
chans = []

# So we go through all possible channels and make lines (for each channel), so they are always present
# Then we will change the data backing each particular line as things come in.
for chan in range(64):
    line = ax.plot(np.linspace(xmin, xmax, 10), [0]*10, linestyle=('solid' if chan < 31 else 'dashed'))[0]
    line.set_label('Channel %d' % chan)
    lines.append(line)
    chans.append(chan)

# We definitely have to hold things fixed, or else the scale will change with every pulse...
ax.set_ylim(-5000, 5000)
ax.set_xlim(xmin, xmax)
ax.set_ylabel("Milivolts")
ax.set_xlabel("Some unit of time between capacitors")
ax.legend()
zeros = np.zeros((1024), dtype=np.int16)
dom = range(1024)

def animate(i):

    # Get one off the deque
    event = events.popEvent()

    for chan,line in enumerate(lines):
        if chan in event.channels.keys():
            line.set_data(dom, gain * event.channels[chan])
        else:
            line.set_data(dom, zeros)

    # Returning a global, what could go wrong?
    return lines#,

ani = animation.FuncAnimation(fig, animate, interval=10, blit=True, save_count=10)
plt.show()

