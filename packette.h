#include <stdint.h>

// DRS4 specific stuff
#define CAP_LEN 1024
#define CAP_LEN_DIV2 512

// power of 2 for the receiving architecture pointer width
#define ARCHITECTURE_WIDTH 8

// ENDIANNESS: These are in little endian so that they can be written as words
//             directly to uncast memory
#define OVERFLOW_FLAG 0x0100
#define UNDERFLOW_FLAG 0x0200
#define NO_DATA_FLAG 0x0400

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
  uint8_t board_id[6];     // 6 bytes: board MAC address (magic)
  uint16_t rel_offset;     // 2 bytes: Sample offset (relative to DRS4_STOP)
  uint64_t seqnum;          // 8 bytes: monotonically increases for each packet!!
};

// 16 bytes
struct header {
  uint32_t event_num;      // 4 bytes: event number (used during assembly)
  uint32_t trigger_low;      // 4 bytes: trigger time low
  uint64_t channel_mask;    // 8 bytes: channels present in this event
};

// 8 bytes + length
struct channel {

  uint16_t num_samples;    // 2 bytes: Number of samples in this fragment
  uint16_t channel;        // 2 bytes: Channel identifier
  uint16_t total_samples;  // 2 bytes: Total number of samples across all fragments 
  uint16_t drs4_stop;      // 2 bytes: DRS4_STOP value

  int16_t samples[0];     // 0 length.  Casted pointer to the first sample
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


