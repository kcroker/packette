#!/usr/bin/python3
import numpy as np
import sys
import time

# We're gonna really streamline this
import multiprocessing

# Ploxy
import matplotlib.pyplot as plt

import packette_stream as packette
#from packette_pedestal import pedestal

# Load some events
events = packette.packetteRun(sys.argv[1:], SCAView=True)

# Display some information
print("Browsing run described by: ", sys.argv[1:])

run = list(enumerate(events))

i = 0

while True:
    
    pos, event = run[i]
    print(" -- Ready to inspect event at position %d in the run. --\n%s" % (i, event), end='')
    print("cachedViews are in " + ("capacitor ordering (e.g. SCA)" if events.SCAView else "time ordering (i.e. stop sample is first)"))
    choice = input("Press [n]ext, [p]revious, [c]hannel [number], [g]raph [number], jump to position [number], [t]oggle view, [q]uit: ")

    cmd = choice.lower()

    if cmd == 'n':
        if i+1 == len(run):
            print("End of run.")
        else:
            i += 1
    elif cmd == 't':
        events.setSCAView(not events.SCAView)
    elif cmd == 'p':
        if i > 0:
            i -= 1
        else:
            print("Start of run.")
    elif cmd == 'q':
        exit(0)
    elif cmd[0] == 'c':
        try:
            cmd, var = cmd.split()
        except:
            print("You must specify a channel number")
            continue
        var = int(var)
        if var in event.channels:
            print(event.channels[var])
        else:
            print("Channel not present in this event")

    elif cmd[0] == 'g':
        plt.cla()

        plt.xlabel('Capacitor')
        plt.ylabel('ADC value')
        plt.grid(True)

        try:
            cmd, var = cmd.split()
            low,high = var.split('-')

            low = int(low)
            high = int(high)

            if low < high and low >= 0 and high < 64:
                plt.title("Event %d, Channels %d-%d" % (event.event_num, low, high))
                
                for n in range(low,high):
                    try:
                        chan = event.channels[n]
                        plt.plot(range(0,1024), chan[0:1024])
                    except:
                        pass

                plt.show(block=False)
        except:
            try:
                var = int(var)
                if var in event.channels:
                    chan = event.channels[var]
                    plt.plot(range(0,1024), chan[0:1024], )

                    plt.title("Event %d, Channel %d" % (event.event_num, var))
                    plt.show(block=False)
                else:
                    print("Channel not present in this event")
            except:
                print("Did not know how to interpret your g")
        
    elif cmd[0] == 'j':
        try:
            cmd, var = cmd.split()
        except:
            print("You must specify a channel number")
            continue
        var = int(var)
        if var < 0 or var >= len(run):
            print("Invalid event position")
        else:
            i = var
        
    print('')
    

