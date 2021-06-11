#!/usr/bin/python3

import cmd, sys, subprocess
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import packette_stream as packette
import argparse
import numpy as np
import os
import readline
import A2x_common

parser = argparse.ArgumentParser(description='Realtime packette data inspector. Can browse existing packette data files or (slowly) capture and new, single-port, streams')
parser.add_argument('--capture', action='store_true', help='Interpret arguments as an IP address and UDP port to listen at')
parser.add_argument('fnames', type=str, nargs='+', help='Files to load or IP address and port')

args = parser.parse_args()

targetport = None
capture = args.capture
target = None

if args.capture:
    try:
        args.fnames = (args.fnames[0], int(args.fnames[1]))
        targetport = args.fnames[1]
    except ValueError as e:
        print("ERROR: Could not interpret %s as a port" % args.fnames[1])
        exit(1)
        
# Load some events
events = packette.packetteRun(args.fnames, SCAView=True)

# Display some information
#board_id = ':'.join(events.board_id.hex()[i:i+2] for i in range(0,12,2))
print("Browsing run described by: ", args.fnames)

histf = '.packette_browse_history'

# This contains an ordered list of event numbers present within
# the run (possibly coming from many distinct files)
run = events.getArrivalOrderedEventNumbers()

i = 0
pos = None
event = None

def stream_next():
    global event, i
    
    if event is None:
        print("No current event!")
        return False
    
    if i+1 >= len(run):
        print("End of run.")
        return False
    else:
        i += 1
        stream_current()
        return True
    
def stream_prev():
    global event, i
    
    if event is None:
        print("No current event!")
        return
    
    if i > 0:
        i -= 1
        stream_current()
    else:
        print("Start of run.")

import traceback
    
def stream_current():
    global event, i

    # Update da kine
    try:
        event = events[run[i]]

        # Output it
        print(event)

        # Print out ordering
        if events.property_stash.SCAView:
            print("Data is rendered in capacitor ordering")
        else:
            print("Data is rendered in time ordering")
            
    except Exception as e:
        #print(e)
        #traceback.print_tb(e.__traceback__)
        print("No events yet in stream...")


#
# Capture arrow keys and shift arrow keys?
#   Left, Right: translate last written interval or single to the Left/Right in channel space
#   Shift+L/R: symmetrically dilate/contract last written interval about its center in channel space
#   Up, Down: translate last written interval or single to the Up/Down in event space
#   Shift+Up/Down: symmetrically dilate/contract last written interval about its center in event space
#   q: return to the command line
#
# Not sure how to do this with GNU Readline....

def toggle_view():
    events.setSCAView(not events.property_stash.SCAView)

    if events.property_stash.SCAView:
        print("Cached views are now capacitor-ordered")
    else:
        print("Cached views are now time-orderd")
        
def switch_channel(args):
    global event, i
    
    if event is None:
        print("No current event!")
        return
    
    var = int(args)
    if var in event.channels:
        print(event.channels[var])
        print("cachedViews are in " + ("capacitor ordering (e.g. SCA)\n" if events.property_stash.SCAView else "time ordering (i.e. stop sample is first)\n"))

    else:
        print("Channel %d not present in this event" % var)

import re
def parse_speclist(speclist):

    # Speclist looks like
    # [!]n1, [!]n2-n3, [!]s(x), [!]s(x)-s(y)...

    # Make a regex for matching strip
    p = re.compile(r's\((.*)\)')
    
    # Received
    print("Received: ", speclist)
    
    # Get the individual specs
    specs = [x.strip() for x in speclist.split(',')]

    exclusions = []
    inclusions = []
    
    for spec in specs:

        # See if they are negated
        negated = False
        if spec[0] == '!':
            negated = True
            spec = spec[1:]
            
        try:
            # First see if its a tile strip
            m = p.match(spec)
            if not m is None:

                # Extract the strip number as a string
                m = m.group(1)

                print("Matched", m)
                
                # Get strip tuples of channels
                tuples = [A2x_common.strips[s] for s in parse_speclist(m)]

                # Inefficient comparison ::puke::
                for tup in tuples:
                    if negated:
                        exclusions += tup
                    else:
                        inclusions += tup 
            else:        
                # Extract the bounds
                bounds = [int(x) for x in spec.split('-')]

                # Double up if necessary
                if len(bounds) < 2:
                    bounds.append(bounds[0])
                
                # Flip the if reversed
                if bounds[0] > bounds[1]:
                    tmp = bounds[1]
                    bounds[1] = bounds[0]
                    bounds[0] = tmp

                # Add it to the appropriate list
                # Interpret bounds as inclusive
                if negated:
                    exclusions += range(bounds[0], bounds[1]+1)
                else:
                    inclusions += range(bounds[0], bounds[1]+1)

        except ValueError as e:
            print("Did not understand %s, skipping..." % spec)


    print("Include: ", inclusions)
    print("Exclude: ", exclusions)
    
    # Filter out the exclusions from the inclusions
    return [x for x in inclusions if x not in exclusions]
                                
def graph(arg):

    global run,i
    
    # Number of valid directives
    graphs = []
    
    # Interpret as semi-colon separated individual directives
    directives = [x.strip() for x in arg.split('&')]

    eventcnt = 0
    
    # Each directive looks like
    #  [<event spec>:]<channel spec>

    for directive in directives:

        # Start off assuming the current event
        eventspec = [i]
        chanlist = []
        
        # See if there's a specific list of requested events
        try:
            specs = [x.strip() for x in directive.split(':')]
            if len(specs) > 1:
                eventspec = parse_speclist(specs[0])
                chanlist = parse_speclist(specs[1])
            else:
                chanlist = parse_speclist(specs[0])
            
        except ValueError as e:
            print("Could not understand ", directive)
            continue
        
        # Iterate over events
        for eventpos in eventspec:
            for n in chanlist:
                try:
                    graphs.append((events[run[eventpos]].channels[n], eventpos, n))
                except (KeyError, StopIteration) as e:
                    print("Missing Event %d, Channel %d?" % (eventpos,n))

        # Event count for alphap
        eventcnt += len(eventspec)
        
    # # Derp
    # # The dumbest coordinate system
    # ax.axhline(y=4, dashes=(2,2,2,2), color='black', label='No data')
    # ax.axhline(y=8, dashes=(1,1,1,1), color='black', label='Masked')
    # plt.axhspan(0, 8, alpha=0.2, facecolor='cyan', label='Flagged')

    if len(graphs) > 0:
        # Set up the graph
        plt.cla()
        ax = plt.gca()
    
        ax.set_xlabel('Capacitor')
        ax.set_ylabel('ADC value')
        ax.grid(True)
        ax.set_xlim(-5,1030)

        # board id belongs to the event, but we enforce equality across a run
        ax.set_title("Board @ %s, %s ordering" % (event.prettyid(), "capacitor" if events.property_stash.SCAView else "time"))
        
        for chan,eventpos,n in graphs:                    
            plt.plot(range(0,1024), chan[0:1024], label='Event %d, Channel %d' % (eventpos, n), alpha=1 if 2./eventcnt > 1 else 2./eventcnt)

        lgd = ax.legend() #bbox_to_anchor=(1.04,1), loc="upper left")
    
    # ax.add_artist(lgd)

        plt.show(block=False)
                   
            
#     #  a) a channel: 56
#     #  b) a channel range: 34-45
#     #  c)

# def graph(args):
#     global event, pos, i
    
#     if event is None:
#         print("No current event!")
#         return

#     plt.cla()
#     ax = plt.gca()
    
#     ax.set_xlabel('Capacitor')
#     ax.set_ylabel('ADC value')
#     ax.grid(True)
#     ax.set_xlim(0,1025)
#     #ax.axvline(x=1024, dashes=(2,2,2,2), color='black')
    
#     # OOO This is ugly code, merge it to a list containing a single line, and just
#     # graph once

#     chanstograph = None
    
#     try:
#         low,high = args.split('-')
    
#         low = int(low)
#         high = int(high)

#         print("Request to plot channels %d to %d, inclusive" % (low, high))
        
#         if low < high and low >= 0 and high < 64:
#             plt.title("Event %d, Channels %d-%d" % (event.event_num, low, high))
#             chanstograph = range(low,high+1)
#     except ValueError as e:
#         pass

#     try:
#         chanstograph = [int(x) for x in args.split(',')]

#         print("Request to plot many individual channels ", chanstograph)
        
#     except ValueError as e:
#         pass

#     if not chanstograph is None:
        
#         for n in chanstograph:
#             try:
#                 chan = event.channels[n]
#                 plt.plot(range(0,1024), chan[0:1024], label='Channel %d' % n)
#             except:
#                 pass

#         # The dumbest coordinate system
            
#         ax.axhline(y=4, dashes=(2,2,2,2), color='black', label='No data')
#         ax.axhline(y=8, dashes=(1,1,1,1), color='black', label='Masked')
#         plt.axhspan(0, 8, alpha=0.2, facecolor='cyan', label='Flagged')
            
#         lgd = ax.legend(bbox_to_anchor=(1.04,1), loc="upper left")
#         # plt.tight_layout()
#         # ax.add_artist(lgd)
#         plt.show(block=False)
#     else:
#         try:
#             # For singles, show individual masks, overflows, and underflows
            
#             var = int(args)
#             if var in event.channels:
#                 chan = event.channels[var]

#                 # Python cannot do signed bitwise math correctly unless width is
#                 # coming into play?

#                 # Get it in numpy so bitwise works
#                 x = np.arange(1024, dtype=np.int16)
#                 y = chan[0:1024]

#                 # Test your cleverness with the masking
#                 # ~ with signed is going to give you a bad day.
#                 flags = (y & 0xF)
#                 valid = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))
#                 ou = (((flags & 0x2) >> 1) | (flags & 0x1))
                
#                 xvalid = x[valid > 0]
#                 yvalid = y[valid > 0]
#                 validsegs = np.column_stack((xvalid, yvalid))
                                
#                 xou = x[ou > 0]
#                 you = y[ou > 0]
#                 ousegs = np.column_stack((xou, you))
                                  
#                 ax.set_ylim(int(np.min(yvalid)), int(np.max(yvalid)))

#                 # Add some line collections
#                 ax.add_collection(LineCollection([validsegs]))
#                 ax.add_collection(LineCollection([ousegs]))

#                 alreadyLabeled = False
#                 for mlow,mhigh in chan.masks:
#                     plt.axvspan(mlow, mhigh, alpha=0.3, facecolor='gray', label='Masked' if not alreadyLabeled else '')
#                     alreadyLabeled = True
                    
#                 ax.set_title("Event %d, Channel %d" % (event.event_num, var))
#                 ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
#                 plt.show(block=False)
#             else:
#                 print("Channel not present in this event")
#         except Exception as e
#             print(e)
#             print("Could not understand your channel specification")
            
def jump(args):
    global event, i
    
    try:
        var = int(args)
        if var < 0 or var >= len(run):
            print("Invalid event position")
        else:
            i = var
    except:
        print("Could not understand your jump request")

    stream_current()

def export(arg):
    global event

    # Use colon to separate da kine
    try:
        chan,fname = arg.split(':')
    except ValueError as e:
        print("SYNTAX export <channel number>:<filename>")
        return
    
    try:
        chan = int(chan)
        if chan < 0 or chan > 63:
            raise ValueError()
        
    except ValueError as e:
        print("Could not interpret %d as a channel" % chan)
        return
    
    try:
        with open(fname, "wt") as f:
            for n,x in enumerate(event.channels[chan].cachedView):
                print(n, x, file=f)

        print("Exported channel %d to %s" % (chan, fname))
        
    except KeyError as e:
        print("Channel %d does not exist in this event" % chan)
        
def refresh():
    global run

    resptuple = events.updateIndex()
    print("Indexed %d additional events in ~%f seconds" % resptuple)

    # Go to the end
    jump(len(events)-1)
    
# Shell out and run the A2x_tool
def execute(args):

    global target
    print("Running ./A2x_tool.py %s...\n(Output will be displayed upon command completion)" % args)

    arglist = args.split()
    if not target is None:
        arglist.insert(0, "-a %d" % targetport)
        arglist.insert(0, target)

    # Pass these directly to A2x_tool
    results = subprocess.run(["./A2x_tool.py", *arglist], stdout=subprocess.PIPE) 

    # Output the results
    print(str(results.stdout))
    
class PacketteShell(cmd.Cmd):
    global event, run
    
    intro = 'Welcome to packette better_browse.   Type help or ? to list commands.\n'
    prompt_text = "Event #%d @ %d of %d (packette) " 
    
    file = None

    # ----- basic turtle commands -----
    def do_current(self, arg):
        'Display current event information: current'
        stream_current()
    def do_next(self, arg):
        'Advance to the next event within the stream: next'
        stream_next()
    def do_prev(self, arg):
        'Return to the previous event within the stream: prev'
        stream_prev()
    def do_channel(self, arg):
        'Inspect a particular channel of the current event:  channel 5'
        if len(arg) < 1:
            print("Please specify a channel number")
        else:
            switch_channel(arg)
    def do_graph(self, arg):
        'Graph a channel or range of channels: graph 0-31, graph 4'
        if len(arg) == 0:
            arg = '0-63'
            
        graph(arg)        
    def do_toggle(self, arg):
        'Toggle between SCA (capacitor) view and time-ordered: toggle'
        toggle_view()
    def do_jump(self, arg):
        'Jump to an arbitrary event position within the stream:  jump 5'
        jump(arg)
    def do_cmd(self, arg):
        'Runs ./A2x_tool.py <whatever>: e.g. cmd -I -N 20 10.0.6.97 to initialize the board at 10.0.6.97 and then request 20 soft triggers at the default rate'
        execute(arg)
    def do_refresh(self, arg):
        'Rebuild stream index and jump to most recent event: refresh'
        refresh()
    def do_export(self, arg):
        'Export the cached view of a channel in ascii to a file.  e.g. export 5:destination.dat'
        export(arg)
    def do_target(self, arg):
        'In capture mode, aim a board at the listening socket, and make this board the default passed to cmd'  
        global target

        if not args.capture:
            print("Only relevant in --capture mode.  You have loaded files.")
            return False
        
        if len(arg) == 0:
            print("Currently targetted at: %s" % ( "Nothing" if target is None else "%s:%d" % (target, targetport)))
        elif arg == 'off':
            target = None
        else:
            # Since target != None, it'll do the insertion and aim, every time
            target = arg
            execute(' ')
    def do_batch(self, arg):
        'Run commands separated by ; in succession'
        cmds = [x.strip() for x in arg.split(';')]
        for cmd in cmds:
            self.onecmd(cmd)

    def do_ffwd(self, arg):
        'Fast-forward to the next non-empty event'

        global event
        stream_next()
        
        while len(event.channels) == 0 and stream_next():
            pass
                    
        print("You should now be on a non-empty event (or end of run).")
        
    def do_quit(self, arg):
        'Quit'
        self.close()
        return True
    def do_EOF(self, arg):
        'Quit'
        self.close()
        return True

    # ----- record and playback -----
    def do_record(self, arg):
        'Save future commands to filename:  RECORD rose.cmd'
        self.file = open(arg, 'w')
    def do_playback(self, arg):
        'Playback commands from a file:  PLAYBACK rose.cmd'
        self.close()
        with open(arg) as f:
            self.cmdqueue.extend(f.read().splitlines())


    def postcmd(self, stop, line):
        global event, i

        if not event is None:
            self.prompt = self.prompt_text % (event.event_num, i, len(run))
        else:
            print(" -- No events in run yet.  Take data and refresh. -- ")

        # Some of our commands are case sensitive!
        #line = line.lower()
        return stop

    def preloop(self):
        global run, i, event
        stream_current()

        # Load the history file
        if os.path.exists(histf):
            readline.read_history_file(histf)
             
        self.prompt = '(packette) ' if event is None else self.prompt_text % (event.event_num, i, len(run))

    def postloop(self):
        readline.write_history_file(histf)
        
    def precmd(self, line):
        if self.file and 'playback' not in line:
            print(line, file=self.file)
        return line

    def emptyline(self):
        # Do nothing
        stream_current()
        return
    
    def close(self):
        if self.file:
            self.file.close()
            self.file = None
        print('')

if __name__ == '__main__':
    PacketteShell().cmdloop()
