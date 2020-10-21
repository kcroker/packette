#!/usr/bin/python3

# Transport packet format
packette_transport_format = '6s H Q   I I Q   H H H H'

# Make an encoder
packette_transport = struct.Struct(packette_transport_format)

# I got myself a shorty
from collections import namedtuple

field_list = ['board_id',
              'rel_offset',
              'seqnum',

              'event_num',
              'trigger_low',
              'channel_mask',

              'num_samples',
              'channel',
              'total_samples',
              'drs4_stop']

# Got myself a 40
packette_tuple = namedtuple('packette_tuple', field_list)

class packette_run(object):

    # The simple event class, contains a list of packette_channel objects
    # These are backed by numpy arrays, but support indexing beyond the present data
    class packette_event(object):

        def __init__(self, header):
            self.channels = {}

            self.event_num = header['event_num']
            self.trigger_low = header['trigger_low']
            
            # For every channel thats on in the mask, make a dictionary entry to it
            chan = 0
            while chan < 64:
                if header['channel_mask'] & 0x1:
                    self.channels[chan] = packette_channel(0, np.empty([0]))

                # Advance to the next place in the mask
                header['channel_mask'] >>= 1
                chan += 1
                

    # This acts like an array access, except
    # it returns NO_DATA for values that are not
    # defined 
    class packette_channel(object):

        # data is a numpy array
        def __init__(self, drs4_stop, data):
            self.drs4_stop = drs4_stop
            self.data = data
        
        # Length
        def __len__(self):
            return self.data.len()
        
        # Return the data if its there, otherwise return NO_DATA
        def __getitem__(self, key):

            if not isinstance(key, int):
                raise Exception("key must be an integer")
            
            if key < 0 or key > 1024:
                raise Exception("key lies outside of DRS4 switched cap array")

            # Get the offset into the data we have
            i = (self.drs4_stop + key) & 1023

            # Return the data if its there
            if i < self.length:
                return self.data[i]
            else:
                return NO_DATA
            
    def __init__(self, fname):

        self.fname = fname
        self.events = []
        self.header_size = packette_transport.calcsize()
        self.board_id = None

        # Load up the file
        fp = fopen(fname, 'rb')
        
        # Start loading in event data
        prev_event_num = -1
        event = None
        
        while True:

            # Grab a header
            try:
                header = fp.read(header_size)
            except:
                fclose(fp)
                break

            # Unpack it
            header = packette_transport.unpack(header)

            # Are we looking at the same board?
            if self.board_id is None:
                self.board_id = header['board_id']
            else if not self.board_id == header['board_id']:
                raise Exception("ERROR: Heterogenous board identifiers in event stream.\n " \
                                "\tOutput from different boards should be directed to\n " \
                                "\tdistinct packette instances on disjoint port ranges")

            # Did we graduate to a new event?
            if prev_event_number < header['event_num']:

                # If we had been building an event, its done now, add it
                if not event is None:
                    self.events.append(event)
                    prev_event_number = header['event_num']
                    
                # Make a new event
                event = packette_event(header)

            # Populate the channel data from this transport packet
            chan = event.channels[header['channel']]
            
            # Is this the first data for this channel? 
            if chan.len() == 0:
                # Replace the empty with a properly sized numpy array
                chan.drs4_stop = header['drs4_stop']
                chan.data = np.array([header['total_samples']]))
                
            # Read the payload from this packet
            payload = np.frombuffer(self.fp.read(header['num_samples']*SAMPLE_WIDTH), dtype=int16)

            # Write the payload at the relative offset within the numpy array
            chan.data[header['rel_offset']:header['rel_offset'] + header['num_samples']] = payload
            
