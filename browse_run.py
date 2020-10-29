#!/usr/bin/python3
import numpy as np
import sys
import time

# We're gonna really streamline this
import multiprocessing

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
    print("Event at position %d in the run:\n%s" % (i, event))
    choice = input("Press [n]ext, [p]revious, [c]hannel [number], jump to position [number], [q]uit: ")

    cmd = choice.lower()

    if cmd == 'n':
        if i+1 == len(run):
            print("End of run.")
        else:
            i += 1
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
    elif cmd[0] == 'j':
        try:
            cmd, var = cmd.split()
        except:
            print("You must specify a channel number")
            continue
        var = int(var)
        if var < 0 or var > len(run):
            print("Invalid event position")
            i = var
        
        

