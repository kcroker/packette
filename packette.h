// DRS4 specific stuff
#define CAP_LEN 1024
#define CAP_LEN_DIV2 512

// power of 2 for the receiving architecture pointer width
#define ARCHITECTURE_WIDTH 8

#define OVERFLOW_FLAG 0x0001
#define UNDERFLOW_FLAG 0x0002
#define NO_DATA_FLAG 0x0004

// Used for writing 8 bytes of no data quickly
#define NO_DATA_FLAG_4X 0x0004000400040004

// Maximum fragment size (in samples)
#define MAX_FRAGMENT_WIDTH 512

// How many bytes per sample (2 for 12 bit ADC)
#define SAMPLE_WIDTH 2

// How many channels?
#define NUM_CHANNELS 64

#if (NUM_CHANNELS > 64)
#error "In this version, channel masks are encoded using a 64-bit long."
#endif

//
// Run header - that allows reproduction of board state.
// This is a separate thing.
//

//////////////////////// PACKETTE TRANSPORT PROTOCOL BEGIN ////////////////////////////

// NOTE:
// The structures are separate for packing and reuse in the storage protocol

// 16 bytes
struct assembly {
  unsigned char board_id[6];     // 6 bytes: board MAC address (magic)
  unsigned short rel_offset;     // 2 bytes: Sample offset (relative to DRS4_STOP)
  unsigned long seqnum;          // 8 bytes: monotonically increases for each packet!!
};

// 16 bytes
struct header {
  unsigned int event_num;      // 4 bytes: event number (used during assembly)
  unsigned int trigger_low;      // 4 bytes: trigger time low
  unsigned long channel_mask;    // 8 bytes: channels present in this event
};

// 8 bytes + length
struct channel {

  unsigned char reserved[3];     // 3 bytes: 0x00 0x00 0x00 (at the top for alignment)
  unsigned char channel;         // 1 byte:  Channel identifier
  unsigned short num_samples;    // 2 bytes: Total number of samples across all fragments 
  unsigned short drs4_stop;      // 2 bytes: DRS4_STOP value

  unsigned short samples[0];     // 0 length.  Casted pointer to the first sample
};

//
// These are quantities that will be shipped out on each packet
// for fastest reconstruction.
//
// 40 byte header - x86 64bit cache line is 64 bytes, so we fit.
//
struct packette_transport {
  struct assembly assembly;      // 16 bytes
  struct header header;          // 16 bytes
  struct channel channel;        // 8 bytes + (variable)roi_width*SAMPLE_WIDTH
};

//////////////////////// PACKETTE TRANSPORT PROTOCOL END ////////////////////////////

#define BUFSIZE (sizeof(struct packette_transport) + MAX_FRAGMENT_WIDTH*SAMPLE_WIDTH)

////////////////////// CONSTRAINTS ////////////////////////
//
//    roi_width * SAMPLE_WIDTH must be a multiple of 8
//
//
// MACROS
// XXX (these are probably broken right now)
 
// Returns a pointer to the head of the Nth event
#define EVENT(N, packet) ( (unsigned short *) ( (packet).data + ( (sizeof struct channel_block) + (packet).roi_width) * active_channels * (N) ) )

// Returns a pointer to the head of the requested channel of the Nth event if present, otherwise returns NULL
#define CHANNEL(channel, packet)  ( (unsigned short *) ( (packet).channel_map[(channel)] < 0 ? 0x0 : (packet).channel_map[(channel)]*( (packet).roi_width + (sizeof struct channel_block)) ) )

