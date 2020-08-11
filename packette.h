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

// Maximum payload size (in bytes)
#define MAX_PAYLOAD 1024

// How many bytes per sample (2 for 12 bit ADC)
#define SAMPLE_WIDTH 2

// How many channels?
#define NUM_CHANNELS 64

//
// This quantity is only needed during assembly and is omitted otherwise
//
struct assembly {
  unsigned long cap_offset;     // Writing offset during assembly
};

//
// In the final data stream, this will only occur once at the start of the data.
// In particular, seqnum will be the starting event number.
//
// In data streamed from the board, this header is present in every packet
//
struct header {
  unsigned long seqnum;         // This now monotonically increases across events and individual fragmented packets.
  unsigned long channel_mask;   // 64 bit mask on which channels were enabled (to distinguish from zero suppression)
  unsigned long roi_width;      // How large the ROI mode was (how many samples are we expecting)
};

// 8 bytes
struct channel_block {
  unsigned long channel;        // This is the device channel
  unsigned long drs4_stop;      // This is where the sampling stopped.  Sits here because there are many DRS4s.
  unsigned int samples[0];      // This will always be roi_length when reconstructed or some fragment length, divisible by 8
};

//
// These are quantities that will be shipped out on each packet
// for fastest reconstruction.
//
struct packette_raw {
  struct assembly assembly;
  struct header header;
  struct channel_block data;
};

//
// This is the format of the final written file
//
struct packette_processed {

  struct header header;

  // Convenience quantities
  unsigned char active_channels;
  char channel_map[NUM_CHANNELS];
		   
  // Here be dragons
  struct channel_block data[0];  
};

// 
// MACROS
// XXX (these are probably broken right now)
 
// Returns a pointer to the head of the Nth event
#define EVENT(N, packet) ( (unsigned short *) ( (packet).data + ( (sizeof struct channel_block) + (packet).roi_width) * active_channels * (N) ) )

// Returns a pointer to the head of the requested channel of the Nth event if present, otherwise returns NULL
#define CHANNEL(channel, packet)  ( (unsigned short *) ( (packet).channel_map[(channel)] < 0 ? 0x0 : (packet).channel_map[(channel)]*( (packet).roi_width + (sizeof struct channel_block)) ) )

