#!/usr/bin/python3

import cmd, sys, subprocess
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import packette_stream as packette
import argparse
import numpy as np

parser = argparse.ArgumentParser(description='Realtime packette data inspector. Can browse existing packette data files or (slowly) capture and new, single-port, streams')
parser.add_argument('--capture', action='store_true', help='Interpret arguments as an IP address and UDP port to listen at')
parser.add_argument('fnames', type=str, nargs='+', help='Files to load or IP address and port')

args = parser.parse_args()

if args.capture:
    try:
        args.fnames = (args.fnames[0], int(args.fnames[1]))
    except ValueError as e:
        print("ERROR: Could not interpret %s as a port" % args.fnames[1])
        exit(1)
        
# Load some events
events = packette.packetteRun(args.fnames, SCAView=True)

# Display some information
#board_id = ':'.join(events.board_id.hex()[i:i+2] for i in range(0,12,2))
print("Browsing run described by: %s\n" % args.fnames)

run = list(enumerate(events))

i = 0
pos = None
event = None

def stream_next():
    global event, pos, i
    
    if event is None:
        print("No current event!")
        return
    
    if i+1 >= len(run):
        print("End of run.")
    else:
        i += 1
        stream_current()

def stream_prev():
    global event, pos, i
    
    if event is None:
        print("No current event!")
        return
    
    if i > 0:
        i -= 1
        stream_current()
    else:
        print("Start of run.")

def stream_current():
    global event, pos, i

    # Update da kine
    try:
        pos, event = run[i]

        # Output it
        print(event)
    except:
        print("No events yet in stream...")
    
def toggle_view():
    events.setSCAView(not events.SCAView)

def switch_channel(args):
    global event, pos, i
    
    if event is None:
        print("No current event!")
        return
    
    var = int(args)
    if var in event.channels:
        print(event.channels[var])
        print("cachedViews are in " + ("capacitor ordering (e.g. SCA)\n" if events.SCAView else "time ordering (i.e. stop sample is first)\n"))

    else:
        print("Channel %d not present in this event" % var)

def graph(args):
    global event, pos, i
    
    if event is None:
        print("No current event!")
        return

    plt.cla()
    ax = plt.gca()
    
    ax.set_xlabel('Capacitor')
    ax.set_ylabel('ADC value')
    ax.grid(True)
    ax.set_xlim(0,1025)
    #ax.axvline(x=1024, dashes=(2,2,2,2), color='black')
    
    # OOO This is ugly code, merge it to a list containing a single line, and just
    # graph once
    
    try:
        low,high = args.split('-')
    
        low = int(low)
        high = int(high)

        print("Request to plot channels %d to %d, inclusive" % (low, high))
        
        if low < high and low >= 0 and high < 64:
            plt.title("Event %d, Channels %d-%d" % (event.event_num, low, high))
            for n in range(low,high+1):
                try:
                    chan = event.channels[n]
                    plt.plot(range(0,1024), chan[0:1024], label='Channel %d' % n)
                except:
                    pass

            # The dumbest coordinate system
            
            ax.axhline(y=4, dashes=(2,2,2,2), color='black', label='No data')
            ax.axhline(y=8, dashes=(1,1,1,1), color='black', label='Masked')
            plt.axhspan(0, 8, alpha=0.2, facecolor='cyan', label='Flagged')
            
            lgd = ax.legend() #bbox_to_anchor=(1.04,1), loc="upper left")
            # plt.tight_layout()
            # ax.add_artist(lgd)
            plt.show(block=False)
    except:
        try:
            # For singles, show individual masks, overflows, and underflows
            
            var = int(args)
            if var in event.channels:
                chan = event.channels[var]

                # Python cannot do signed bitwise math correctly unless width is
                # coming into play?

                # Get it in numpy so bitwise works
                x = np.arange(1024, dtype=np.int16)
                y = chan[0:1024]

                # Test your cleverness with the masking
                # ~ with signed is going to give you a bad day.
                flags = (y & 0xF)
                valid = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))
                ou = (((flags & 0x2) >> 1) | (flags & 0x1))
                
                xvalid = x[valid > 0]
                yvalid = y[valid > 0]
                validsegs = np.column_stack((xvalid, yvalid))
                                
                xou = x[ou > 0]
                you = y[ou > 0]
                ousegs = np.column_stack((xou, you))
                                  
                ax.set_ylim(int(np.min(yvalid)), int(np.max(yvalid)))

                # Add some line collections
                ax.add_collection(LineCollection([validsegs]))
                ax.add_collection(LineCollection([ousegs]))

                alreadyLabeled = False
                for mlow,mhigh in chan.masks:
                    plt.axvspan(mlow, mhigh, alpha=0.3, facecolor='gray', label='Masked' if not alreadyLabeled else '')
                    alreadyLabeled = True
                    
                ax.set_title("Event %d, Channel %d" % (event.event_num, var))
                ax.legend()
                plt.show(block=False)
            else:
                print("Channel not present in this event")
        except Exception as e:
            print(e)
            print("Could not understand your channel specification")
            
def jump(args):
    global event, pos, i
    
    try:
        var = int(args)
        if var < 0 or var >= len(run):
            print("Invalid event position")
        else:
            i = var
    except:
        print("Could not understand your jump request")

    stream_current()
    
def refresh():
    global run
    events.updateIndex()
    run = list(enumerate(events))
    jump(len(events)-1)
    stream_current()

# Shell out and run the A2x_tool
def execute(args):

    print("Running ./A2x_tool.py %s...\n(Output will be displayed upon command completion)" % args)
    
    # Pass these directly to A2x_tool
    results = subprocess.run(["./A2x_tool.py", *args.split()], stdout=subprocess.PIPE)

    # Output the results
    print(str(results.stdout))
    
class PacketteShell(cmd.Cmd):
    global event, pos
    
    intro = 'Welcome to packette better_browse.   Type help or ? to list commands.\n'
    prompt_text = "Event #%d @ %d (packette) " 
    
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
        graph(arg)
    def do_toggle(self, arg):
        'Toggle between SCA (capacitor) view and time-ordered: toggle'
        toggle_view()
    def do_jump(self, arg):
        'Jump to an arbitrary event position within the stream:  jump 5'
        jump(arg)
    def do_cmd(self, arg):
        'cmd ./A2x_tool.py <whatever>: e.g. -I -N 20 10.0.6.97 to initialize the board at 10.0.6.97 and then request 20 soft triggers at the default rate'
        execute(arg)
    def do_refresh(self, arg):
        'Rebuild stream index and jump to most recent event: refresh'
        refresh()
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
        global event, pos, i

        if not event is None:
            self.prompt = self.prompt_text % (event.event_num, pos)
        else:
            print(" -- No events in run yet.  Take data and refresh. -- ")

        # Some of our commands are case sensitive!
        #line = line.lower()
        return stop

    def preloop(self):
        stream_current()
        self.prompt = '(packette) ' if event is None else self.prompt_text % (event.event_num, pos)
        
    def precmd(self, line):
        if self.file and 'playback' not in line:
            print(line, file=self.file)
        return line
    
    def close(self):
        if self.file:
            self.file.close()
            self.file = None
        print('')

if __name__ == '__main__':
    PacketteShell().cmdloop()
