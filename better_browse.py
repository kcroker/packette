#!/usr/bin/python3

import cmd, sys
import matplotlib.pyplot as plt
import packette_stream as packette

if len(sys.argv) < 2:
    print("Please specify a set of packette run files")
    exit(1)
    
# Load some events
events = packette.packetteRun(sys.argv[1:], SCAView=True)

# Display some information
print("Browsing run described by: ", sys.argv[1:])

run = list(enumerate(events))

i = 0
pos = None
event = None

def stream_next(args):
    if i+1 >= len(run):
        print("End of run.")
    else:
        i += 1

def stream_prev(args):
    if i > 0:
        i -= 1
    else:
        print("Start of run.")

def toggle_view(args):
    events.setSCAView(not events.SCAView)

def switch_channel(args):

    if event is None:
        return
    
    var = int(args)
    if var in event.channels:
        print(event.channels[var])
    else:
        print("Channel %d not present in this event" % var)

def graph(args):

    if event is None:
        return
    
    plt.cla()

    plt.xlabel('Capacitor')
    plt.ylabel('ADC value')
    plt.grid(True)

    try:
        low,high = args.split('-')
    
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
            var = int(args)
            if var in event.channels:
                chan = event.channels[var]
                plt.plot(range(0,1024), chan[0:1024], )

                plt.title("Event %d, Channel %d" % (event.event_num, var))
                plt.show(block=False)
            else:
                print("Channel not present in this event")
        except:
            print("Could not understand your channel specification")
            
def jump(args):
    try:
        var = int(args)
        if var < 0 or var >= len(run):
            print("Invalid event position")
        else:
            i = var
    except:
        print("Could not understand your jump request")

def refresh():
    events.updateIndex()
    jump(len(events)-1)
    pass

# Shell out and run the A2x_tool
def execute():
    pass

class PacketteShell(cmd.Cmd):
    intro = 'Welcome to packette better_browse.   Type help or ? to list commands.\n'
    prompt = '(packette) '
    file = None

    def preloop(self):
        if len(run) > 0:
            pos, event = run[i]
            print(" -- Ready to inspect event at position %d in the run. --\n%s" % (i, event), end='')
            print("cachedViews are in " + ("capacitor ordering (e.g. SCA)" if events.SCAView else "time ordering (i.e. stop sample is first)"))
        else:
            print(" -- No events in run yet.  Take data and refresh. -- ")

    # ----- basic turtle commands -----
    def do_next(self, arg):
        'Advance to the next event within the stream: next'
        stream_next(*parse(arg))
    def do_prev(self, arg):
        'Return to the previous event within the stream: prev'
        stream_prev(*parse(arg))
    def do_channel(self, arg):
        'Inspect a particular channel of the current event:  channel 5'
        switch_channel(*parse(arg))
    def do_graph(self, arg):
        'Graph a channel or range of channels: graph 0-31, graph 4'
        graph(*parse(arg))
    def do_toggle(self):
        'Toggle between SCA (capacitor) view and time-ordered: toggle'
        toggle_view()
    def do_jump(self, arg):
        'Jump to an arbitrary event position within the stream:  jump 5'
        jump(*parse(arg))
    def do_cmd(self, arg):
        'cmd ./A2x_tool.py <whatever>: -I -N 20 10.0.6.97'
        execute(*parse(arg))
    def do_refresh(self, arg):
        'Rebuild stream index and jump to most recent event: refresh'
        refresh()
    def do_quit(self, arg):
        'Quit'
        self.close()
        quit_browse()
        return True
    
    # def do_position(self, arg):
    #     'Print the current turtle position:  POSITION'
    #     print('Current position is %d %d\n' % position())
    # def do_heading(self, arg):
    #     'Print the current turtle heading in degrees:  HEADING'
    #     print('Current heading is %d\n' % (heading(),))
    # def do_color(self, arg):
    #     'Set the color:  COLOR BLUE'
    #     color(arg.lower())
    # def do_undo(self, arg):
    #     'Undo (repeatedly) the last turtle action(s):  UNDO'
    # def do_reset(self, arg):
    #     'Clear the screen and return turtle to center:  RESET'
    #     reset()
    # def do_bye(self, arg):
    #     'Stop recording, close the turtle window, and exit:  BYE'
    #     print('Thank you for using Turtle')
    #     self.close()
    #     bye()
    #     return True

    # ----- record and playback -----
    def do_record(self, arg):
        'Save future commands to filename:  RECORD rose.cmd'
        self.file = open(arg, 'w')
    def do_playback(self, arg):
        'Playback commands from a file:  PLAYBACK rose.cmd'
        self.close()
        with open(arg) as f:
            self.cmdqueue.extend(f.read().splitlines())
    def precmd(self, line):
        line = line.lower()
        if self.file and 'playback' not in line:
            print(line, file=self.file)
        return line
    def close(self):
        if self.file:
            self.file.close()
            self.file = None

    
def parse(arg):
    'Convert a series of zero or more numbers to an argument tuple'
    return tuple(map(int, arg.split()))

if __name__ == '__main__':
    PacketteShell().cmdloop()
