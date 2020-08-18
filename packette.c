#define _GNU_SOURCE

// Linux process scheduling
#include <sched.h>

// Sockets
#include <netinet/ip.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>

// Multiprocess
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

// Signals
#include <signal.h>

// Time
#include <time.h>

// Shared memory (for interprocess comms without IPC)
#include <sys/mman.h>

// For total fluff
#include <ncurses.h>

// Local stuff
#include "packette.h"

#define DEBUG

///////////////////////////// GLOBALS /////////////////////////

// Note that things are unsigned long because we want to avoid implicit casts
// during computation.
unsigned long (*process_packets_fptr)(void *buf,
				      struct mmsghdr *msgs,
				      int vlen,
				      FILE *ordered_file,
				      FILE *orphan_file);

unsigned long *emptyBlock;

// This is used to signal that we should cleanup
volatile sig_atomic_t interrupt_flag = 0;

//
// This is the sickness
//
// Made with:
//   http://patorjk.com/software/taag/
//
char *packette_logo =
"  (                            )                                \n"
"  )\\ )     (         (      ( /(          *   )    *   )        \n"
" (()/(     )\\        )\\     )\\())  (    ` )  /(  ` )  /(   (    \n"
"  /(_)) ((((_)(    (((_)  |((_)\\   )\\    ( )(_))  ( )(_))  )\\   \n"
" (_))    )\\ _ )\\   )\\___  |_ ((_) ((_)  (_(_())  (_(_())  ((_)  \n"
" | _ \\   (_)_\\(_) ((/ __| | |/ /  | __| |_   _|  |_   _|  | __| \n"
" |  _/    / _ \\    | (__    ' <   | _|    | |      | |    | _|  \n"
" |_|     /_/ \\_\\    \\___|  _|\\_\\  |___|   |_|      |_|    |___| \n";

                                                               
//
// Build channel map.  Returns the number of active channels
// Assumes channel map has been initialized.
//
unsigned long buildChannelMap(unsigned long mask, unsigned char *channel_map) {

  unsigned long active = 0;
  unsigned char i = 0;

  // Note that this short circuits as soon
  // as all the high bits are dead! ::pride::
  for(; mask; mask >> 1) {

    // Check the LSB
    if(mask & 0x1)
      channel_map[i++] = ++active;
  }

  return active;
}

//
// PACKET PROCESSORS
//
unsigned long nop_processor(void *buf, struct mmsghdr *msgs, int vlen, FILE *ordered_file, FILE *orphan_file) {

  unsigned long bytes;
  
  // Oh yeah, we totally processed your packets
  bytes = 0;
  while(vlen--)
    bytes += msgs[vlen].msg_len;
  
  return bytes;
}


unsigned long buffer_dump_processor(void *buf, struct mmsghdr *msgs, int vlen, FILE *ordered_file, FILE *orphan_file) {

  //
  // Writes the entire message buffer at once, including deadspace not necessarily
  // consumed by the packets.
  //
  fwrite(buf,
	 BUFSIZE,
	 vlen,
	 ordered_file);

  return BUFSIZE;
}

unsigned long payload_dump_processor(void *buf, struct mmsghdr *msgs, int vlen, FILE *ordered_file, FILE *orphan_file) {

  struct packette_transport *ptr;
  unsigned long bytes;

  bytes = 0;
  
  //
  // This does nothing but write packet headers and payloads to the ordered file.
  // (This removes buffer garbage)
  //
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // Blast
    fwrite(buf,
	   ptr->channel.num_samples*SAMPLE_WIDTH,
	   1,
	   ordered_file);
    
    bytes += ptr->channel.num_samples*SAMPLE_WIDTH;
    
    // Get the next one
    buf += BUFSIZE;
  }

  return bytes;
}

unsigned long debug_processor(void *buf, struct mmsghdr *msgs, int vlen, FILE *ordered_file, FILE *orphan_file) {

  struct packette_transport *ptr;
  unsigned int i;
  
  //
  // This outputs the headers that come in off the pipe
  //
  char *output =
    "Packette Transport Header:\n"
    "---------------------------\n"
    "Board id:\t\t\t%.2x:%.2x:%.2x:%.2x:%.2x:%.2x\n"
    "Relative offset:\t\t%u\n"
    "Sequence number:\t\t%lu\n"
    "Event number:\t\t\t%u\n"
    "Trigger timestamp (low):\t%u\n"
    "Channel mask:\t\t\t%.2x %.2x %.2x %.2x %.2x %.2x %.2x %.2x\n"
    "Samples (this fragment):\t%u\n"
    "Channel number:\t\t\t%u\n"
    "Total samples (all fragments):\t%u\n"
    "DRS4 stop:\t\t\t%u\n"
    "--------- COMPUTED ---------\n"
    "Payload length (bytes):\t%u\n\n";
  i = 0;
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    fprintf(ordered_file,
	    output,
	    ptr->assembly.board_id[0], ptr->assembly.board_id[1],
	    ptr->assembly.board_id[2], ptr->assembly.board_id[3],
	    ptr->assembly.board_id[4], ptr->assembly.board_id[5],
	    ptr->assembly.rel_offset,
	    ptr->assembly.seqnum,
	    ptr->header.event_num,
	    ptr->header.trigger_low,
	    ((unsigned char *)&(ptr->header.channel_mask))[7],
	    ((unsigned char *)&(ptr->header.channel_mask))[6],
	    ((unsigned char *)&(ptr->header.channel_mask))[5],
	    ((unsigned char *)&(ptr->header.channel_mask))[4],
	    ((unsigned char *)&(ptr->header.channel_mask))[3],
	    ((unsigned char *)&(ptr->header.channel_mask))[2],
	    ((unsigned char *)&(ptr->header.channel_mask))[1],
	    ((unsigned char *)&(ptr->header.channel_mask))[0],
	    ptr->channel.num_samples,
	    ptr->channel.channel,
	    ptr->channel.total_samples,
	    ptr->channel.drs4_stop,
	    msgs[i].msg_len - sizeof(struct packette_transport));
    
    // Get the next one
    buf += BUFSIZE;
    ++i;
  }
  
  return 0;
}

//
// This processor strips headers and writes payloads in 
// defragmented order.
//
// Out of order packets are shunted to orphan_file as
// fixed buffer-length blocks for rapid sorting and
// patching in a second-stage performed offline
//
uint32_t prev_event;
uint64_t prev_seqnum;
void *event;

unsigned long strip_and_order_processor(void *buf,
					struct mmsghdr *msgs,
					int vlen,
					FILE *ordered_file,
					FILE *orphan_file) {

  struct packette_transport *ptr;
  struct packette_event *eptr;
  
  // Iterate over the packets we are given
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // Gotta check sequence number first
    if(ptr->assembly.seqnum < prev->assembly.seqnum) {

      // Immediately buffered write to the orphans
      fprintf(buf,
	      BUFSIZE,
	      1
	      orphan_file);

      // DO NOT update prev_seqnum
    }
    else {

      // Gotta check again so we can drop duplicates
      if(ptr->assembly.seqnum > prev->assembly.seqnum) {

	// Are we in order?
	if(ptr->assembly.seqnum == prev->assembly.seqnum + 1){

	  // Ordered state
	  
	  // Are we still on the same event?
	  if(ptr->header.event_num == prev->header.event_num) {

	    // Are we still on the same channel?
	    if(ptr->channel.channel == prev->channel.channel) {

	      // Pointer should be at the correct location
	      stride = ptr->channel.num_samples*SAMPLE_WIDTH;

	      // Copy just the samples
	      memcpy(eptr,
		     &(ptr->samples),
		     stride);

	      // Advance the intraevent pointer
	      eptr += stride;
	      
	      // Update accounting (for out of order)
	      samples_written += ptr->channel.num_samples;
	    }
	    else {

	      // We have finished a channel.
	      // ===> 1) Write next channel header
	      //      2) Update accounting

	      // Copy over the new channel header and
	      // the first payload fragment
	      //
	      // OOO Consider switching to bytes, because then
	      // I don't have to do a multiplication here
	      stride = sizeof(struct channel) + ptr->channel.num_samples*SAMPLE_WIDTH;
	      memcpy(eptr,
		     &(ptr->channel),
		     stride);

	      // Advance the intraevent pointer
	      eptr += stride;
	      
	      // Update accounting
	      samples_written = ptr->channel.num_samples;
	    }
	  }
	  else {

	    // We have finished an event. 
	    // ===> 1) Write byte totals to memory
	    //      2) Ship it on the ordereds tream
	    //      3) Reset event workbench, copy
	    //         everything
	    //      4) Update accounting

	    // Compute total bytes written via pointer arithmetic
	    *((uint32_t *)event) = (void *)eptr - event;

	    // Write the event
	    fwrite(event,
		   *((uint32_t *)event),
		   1,
		   ordered_file);

	    // Reset the workbench
	    // (notice that we skip the first spot, which
	    //  holds the length of this event)
	    eptr = event + sizeof(uint32_t);

	    // Copy over as much new stuff as possible
	    stride = sizeof(struct header) + sizeof(struct channel) + ptr->channel.num_samples*SAMPLE_WIDTH;
	    memcpy(eptr,
		   &(ptr->header),
		   stride);
	    eptr += stride;
	    
	    // New event: update accounting.
	    samples_written = ptr->channel.num_samples;
	  }
	}
	else {

	  // We've skipped.
	  // Close out anything currently open, possibly shipping.
	  //
	  // If I do this right, I can leave the UDP payload pointer position in the
	  // same place and just have in-order processing resume as normal
	  
	  // Are we still on the same event?
	  if(ptr->header.event_num == prev->header.event_num) {

	    // On same event.
	    // Are we still on the same channel?
	    if(ptr->channel.channel == prev->channel.channel) {

	      //
	      // On same channel.
	      // ===> We droped some number of delay line fragments
	      //

	      //
	      //   samples_written contains the current number of ordered
	      //   samples written.
	      //
	      // We will catch up to this.
	      //
	      // Number of samples in a fragment is
	      // always equal to the ROI width *OR*
	      // the entire delay line, in case of
	      // multiple ROIs
	      //
	      // So seqnum arithmetic tells us how much to write
	      // (note that -1 because we want the number of SKIPPED packets)

	      //
	      // OVERLOAD: stride will be eventually the byte stride in memory
	      //           but we will use it intermediarily to reduce the amount
	      //           of stack construction required to enter this function
	      //
	      stride = ptr->assembly.seqnum - prev->assembly.seqnum - 1;

	      // From delta, we can compute the number of missing bytes
	      stride *= ptr->channel.num_samples;

	      // Account (out of order), so that the meaning of stride remains bytes for the memory
	      // operation
	      samples_written += stride;

	      // Now make stride into bytes
	      stride *= SAMPLE_WIDTH;
	      
	      // Now copy the missing samples from the already
	      // allocated block of empty samples
	      memcpy(eptr,
		     emptySamples,
		     stride);

	      // Update the intraevent pointer
	      eptr += stride;
	    }
	    else {

	      //
	      // We have switched channels, but of the same event.
	      // ===> 1) Close out the remaining bytes of
	      //         of the previous channel.
	      //      2) Memory write header for new channel
	      //      3) Memory Write samples
	      //      4) Reset tracking quantities?
	      //

	      // Q: How we compute the remaining bytes of the previous channel?
	      // A: samples_written
	      stride = prev->channel.total_samples - samples_written;

	      // Out of order accounting to update
	      samples_written += stride;

	      // Now make stride a byte stride
	      stride *= SAMPLE_WIDTH;

	      // Now copy the missing samples from the already
	      // allocated block of empty samples
	      memcpy(eptr,
		     emptySamples,
		     stride);

	      // Update the intraevent pointer
	      eptr += stride;

	      // Now, handle the new channel data.
	      
	      //
	      // CAVEAT: since we skipped packets, the channel offset might not be zero.
	      //         e.g. we dropped the last fragment of the previous channel,
	      //         and the first fragment of the next channel.
	      //

	      // Write the channel header
	      stride = sizeof(struct channel);
	      memcpy(eptr,
		     &(ptr->channel),
		     stride);
	      eptr += stride;

	      // Write empty data up to the relative offset
	      if(ptr->assembly.rel_offset > 0) {
		stride = ptr->assembly.rel_offset;
		samples_written += stride;
		stride *= SAMPLE_WIDTH;
		memcpy(eptr,
		       emptyBlock,
		       stride);
		eptr += stride;
	      }

	      // Now write the samples that we received
	      stride = ptr->channel.num_samples*SAMPLE_WIDTH;
	      memcpy(eptr,
		     ptr->channel.samples,
		     stride);
 	      eptr += stride;
	      
	      // Update accounting
	      samples_written = ptr->channel.num_samples;
	    }
	  }
	  else {

	    // The big drop case is the hardest.
	    
	    // We have entirely switched events.
	    // ===> 1) Close out the curent event.
	    //      1a) Close out the current channel of the current event.
	    //      1b) Determine the missing channels
	    //      1c) Write empty headers for them
	    //      1d) Ship the event
	    //      2) Write out the new event header
	    //      3) Determine what channels are missing
	    //      4) Write out empty headers for them
	    //      5) Write out the received channel header
	    //      6) Determine missing fragments
	    //      7) Write out empty space for them
	    //      8) Write the received samples
	    
	  }
	}
      }
      else {

	// DUPLICATE UDP PACKET
	// Drop it.
      }
    }
  }
}

//
// Called when the child receives SIGINT
//
void flagInterrupt(int signum) {

  // This is a special volatile signal-safe integer type:
  //  https://wiki.sei.cmu.edu/confluence/display/c/SIG31-C.+Do+not+access+shared+objects+in+signal+handlers
  interrupt_flag = 1;
}

// Might want to divide this by 2 so that you don't take up all the L2 cache ;)
#define L2_CACHE 256000
#define TIMEOUT 1

int main(int argc, char **argv) {

  // Socket stuff
  int sockfd, retval, i;
  struct sockaddr_in sa;
  struct timespec timeout;
  unsigned int vlen;
  
  // recvmmsg() stuff
  struct mmsghdr *msgs;
  struct iovec *iovecs;
  void *buf;
  
  // Multiprocessing stuff
  pid_t pid;
  pid_t *kids;  
  unsigned char children, k;

  // Processor pinning stuff
  cpu_set_t  mask;

  // Argument parsing stuff
  int flags, opt;
  int nsecs, tfnd;
  unsigned short port;
  char *addr_str;

  // Signal handling stuff
  struct sigaction new_action, old_action;

  // Files and data output stuff
  FILE *ordered_file;              // Stage I reconstruction (ordered and stripped) output
  FILE *orphan_file;               // Stage II reconstruction (unordered, raw) output
  struct tm lt;                    // For holding time stuff
  time_t secs;
  char tmp1[1024], tmp2[1024];

  // Shared memory for performance reporting
  struct timeval parent_timeout;   // timeval, timespec, tm ... ugh
  void *scratchpad;
  volatile unsigned long *packets_processed_ptr, *bytes_processed_ptr;
  unsigned long *previous_processed;
  unsigned long packets_processed, bytes_processed;
  char output[4906];
  float total_kpps, total_MBps, total_MB, total_Mp;
  
  // lol "basic" shit in C is annoying.
  // Default values
  port = 1338;
  children = 1;
  addr_str = 0x0;
  tmp1[0] = 0x0;
  ordered_file = 0x0;
  
  /////////////////// ARGUMENT PARSING //////////////////
  
  while ((opt = getopt(argc, argv, "t:p:n:o")) != -1) {
    switch (opt) {
    case 't':
      children = atoi(optarg);
      break;
    case 'p':
      port = atoi(optarg);
      break;
    case 'n':
      strncpy(tmp1, optarg, 1024); 
      break;
    case 'o':
      ordered_file = stdout;
      break;
    default: /* '?' */
      fprintf(stderr, "Usage: %s [-t threads] [-p base UDP port] [-n output file prefix] [-o dump to standard out] BIND_ADDRESS\n",
	      argv[0]);
      exit(EXIT_FAILURE);
    }
  }

  // Sanity check
  if(ordered_file) {

    if(children > 1) {
      fprintf(stderr, "ERROR: Multiprocess dump to stdout is stupid.\n");
      exit(EXIT_FAILURE);
    }
    
    fprintf(stderr, "Packette (parent): dumping to stdout...\n");
  }

  // Now grab mandatory positional arguments
  if(optind >= argc) {
    fprintf(stderr, "Expected bind address after options\n");
    exit(EXIT_FAILURE);
  }

  // Get the IP address
  addr_str = argv[optind];

  // Try to parse it out
  if(!inet_pton(AF_INET, addr_str, &(sa.sin_addr))) {
    perror("inet_pton()");
    exit(EXIT_FAILURE);
  }
    
  // Report what we've been asked to do
  fprintf(stderr,
	  "Packette (parent): %d children will bind at %s, starting from port %d\n",
	  children,
	  argv[optind],
	  port);

  ///////////////// PARSING COMPLETE ///////////////////
  
  // Set the initial packet processing pointer to the preprocessor
  process_packets_fptr = &debug_processor;

  // Now compute the optimal vlen via truncated idiv
  vlen = L2_CACHE / BUFSIZE;
  fprintf(stderr,
	  "Packette (parent): Determined %d packets will saturate L2 cache of %d bytes\n",
	  vlen,
	  L2_CACHE);
  
  //
  // No IPC is required between children
  // but we want the children to receive the Ctrl+C and clean themselves up
  // before the parent goes away.
  //
  pid = 1;
  if( ! (kids = (pid_t *)malloc(sizeof(pid_t) * children))) {
    perror("malloc()");
    exit(EXIT_FAILURE);
  }

  // Make the filename?
  if(tmp1[0] == 0x0) {
    secs = time(NULL);
    localtime_r(&secs, &lt);
    strftime(tmp1, 1024, "%Y-%m-%d_%H-%M-%S", &lt);
  }

  fprintf(stderr, "Packette (parent): Using output prefix '%s'\n", tmp1);

  // Allocated shared memory for performance statistics
  if(! (scratchpad = mmap(NULL,
			  children*sizeof(unsigned long)*2,
			  PROT_READ | PROT_WRITE,
			  MAP_SHARED | MAP_ANONYMOUS,
			  -1,
			  0))) {

    perror("mmap()");
    exit(EXIT_FAILURE);
  }
  
  fprintf(stderr, "Packette (parent): Created shared memory scratchpad for performance reporting.\n");
  
  ////////////////////// SPAWNING ////////////////////
  
  // Loop exits when:
  //    pid == 0 (i.e. you're a child)
  //           OR
  //    children == 0 (i.e. you've reached the end of your reproductive lifecycle)
  // Implemented as a negation.
  //
  fprintf(stderr, "Packette (parent): Spawning %d children...\n", children);
  
  k = children;
  while(pid && k) {
    pid = fork();
    if(pid)
      kids[--k] = pid;
  }
  
  //////////////////////// FORKED ////////////////////
  
  if(!pid) {
    ////////////////// CHILD ///////////////////

    // What is our purpose?
    pid = getpid();

    // Pin ourselves to a separate processor
    CPU_ZERO(&mask);
    CPU_SET(k-1, &mask);
    if(sched_setaffinity(0, sizeof(mask), &mask)) {
      perror("sched_setaffinity()");
      fprintf(stderr, "WARNING (PID %d): Unable to pin to CPU %d. (Too many threads?)\n",
	      pid,
	      k-1);
    }
    else
      fprintf(stderr, "Packette (PID %d): Pinned self to CPU %d.\n",
	      pid,
	      k-1);
    
    // Install signal handler so we cleanly flush packets
    // From GNU docs:
    //  https://www.gnu.org/software/libc/manual/html_node/Sigaction-Function-Example.html
    new_action.sa_handler = &flagInterrupt;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    ////////////////// STREAMS //////////////////
       	    
    // Open streams for output
    if(!ordered_file) {
      
      sprintf(tmp2, "%s_%s_%d.ordered", tmp1, addr_str, port + k - 1);
      if( ! (ordered_file = fopen(tmp2, "wb"))) {
	perror("fopen()");
	exit(EXIT_FAILURE);
      }
    }
    
    sprintf(tmp2, "%s_%s_%d.orphans", tmp1, addr_str, port + k - 1);
    
    // Open streams for output
    if( ! (orphan_file = fopen(tmp2, "wb"))) {
      perror("fopen()");
      exit(EXIT_FAILURE);
    }
    
    // Get ready to receive multiple messages on a socket!
    // Code adapted from: man 2 recvmmsg, EXAMPLE

    // Get a socket
    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd == -1) {
      perror("socket()");
      exit(EXIT_FAILURE);
    }

    // Set the port with proper endianness
    sa.sin_port = htons(port + k - 1);
    sa.sin_family = AF_INET;

    // Why does this always have an explicit cast in the examples?
    // I guess so the code block is self-explanatory...
    if (bind(sockfd, &sa, sizeof(sa)) == -1) {
      perror("bind()");
      exit(EXIT_FAILURE);
    }

    // Report success
    fprintf(stderr,
	    "Packette (PID %d): Listening at %s:%d...\n",
	    pid,
	    addr_str,
	    port + k - 1);
        
    // Now need to allocate the message structures
    retval =
      (msgs = (struct mmsghdr *)malloc( sizeof(struct mmsghdr) * vlen)) &&
      (iovecs = (struct iovec *)malloc( sizeof(struct iovec) * vlen)) &&
      (buf = malloc(BUFSIZE * vlen));
    
    if (!retval) {
      perror("malloc()");
      exit(EXIT_FAILURE);
    }
    
    // Report success.
    fprintf(stderr,
	    "Packette (PID %d): Allocated %d bytes for direct socket transfer of %d packets.\n",
	    pid,
	    BUFSIZE * vlen,
	    vlen);
    
    // Now we do the magic.
    // We read in directly to payload buffers, which are offsets into a contiguous block
    memset(msgs, 0, sizeof(struct mmsghdr) * vlen);
    
    // Set this up to directly transfer payloads
    for (i = 0; i < vlen; i++) {
      iovecs[i].iov_base         = buf + i*(BUFSIZE);         // This should be a correctly operating pointer arithmetic...
      iovecs[i].iov_len          = BUFSIZE;
      msgs[i].msg_hdr.msg_iov    = &iovecs[i];
      msgs[i].msg_hdr.msg_iovlen = 1;
    }

    ///////////////////// PERFORMANCE ///////////////////

    // Set up volatile pointers into the shared memory
    packets_processed_ptr = (unsigned long *)scratchpad + 2*(k-1);
    bytes_processed_ptr = (unsigned long *)scratchpad + 2*(k-1)+1;

    *packets_processed_ptr = 0;
    *bytes_processed_ptr = 0;
    
    timeout.tv_sec = TIMEOUT;
    timeout.tv_nsec = 0;

    // Now pull packets in bulk
    // Pull as many as will fit in L2 cache on your platform
    while(1) {

      // Try to grab at most vlen packets, timing out after TIMEOUT
      retval = recvmmsg(sockfd, msgs, vlen, 0, &timeout);

#undef DEBUG
#ifdef DEBUG
      fprintf(stderr,
	      "Packette (PID %d): Received %d packets.\n",
	      pid,
	      retval);
#endif
      
      // Process only the packets received
      if (retval > 0) {

	// XXX? Maybe we don't need to use the __atomic_X operations?
	//
	// Since these are flagged as volatile, this could be super slow
	// since flagged as volatile... (lots of cache misses)
	// Guess we'll find out... this might be why Solarflare's code
	// ran so poorly?
	*bytes_processed_ptr += (*process_packets_fptr)(buf, msgs, retval, ordered_file, orphan_file);
	*packets_processed_ptr += retval;
      }
      else {

	// If there was trouble, see if there was an interrupt
	if (retval == -1) {
	  perror("recvmmsg()");

	  // Check for a Ctrl+C interrupt
	  // Only check the volatile if the socket read got disrupted
	  if(interrupt_flag) {
	    
	    // Someone pressed Ctrl+C
	    fprintf(stderr,
		    "Packette (PID %d): Received SIGINT, finishing up...\n",
		    pid);
	    break;
	  }
	}
      }
    }

    // Close the file descriptors
    fclose(ordered_file);
    fclose(orphan_file);
    
    // Free the scatter-gather buffers
    free(buf);

    // Free the message structures themselves
    free(iovecs);
    free(msgs);

    fprintf(stderr,
	    "Packette (PID %d): Done.\n",
	    pid);
  }
  else {
    ////////////////// PARENT //////////////////

    // Capture SIGINT
    new_action.sa_handler = &flagInterrupt;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    // Allocate and initialize some local accounting for da kids
    if(!(previous_processed = (unsigned long *)malloc(sizeof(unsigned long)*children*2))) {
      perror("malloc()");
      exit(EXIT_FAILURE);
    }

    // Zero it out
    memset(previous_processed, 0x0, sizeof(unsigned long)*children*2);

    //////////////////////////// PERFORMANCE REPORTING /////////////////////

    if(ordered_file != stdout) {
	 
      // Enter ncurses mode
      initscr();

      // Print out a message and table header
      mvprintw(0, 0, packette_logo);
      mvprintw(9, 1, "PID");
      mvprintw(9, 1+6, "| Instantaneous rate");
      mvprintw(9, 1+6+33, "| Cumulative data");
      mvprintw(10, 0, "-----------------------------------------------------------------");
    }
    
#define REFRESH_PERIOD 100000
    while(1) {

      // Reset timeout
      if(ordered_file != stdout) {
	parent_timeout.tv_sec = 0;
      	parent_timeout.tv_usec = REFRESH_PERIOD;
      }
      else {
	parent_timeout.tv_sec = 1;
	parent_timeout.tv_usec = 0;
      }
	
      // Sit in timeout for exactly TIMEOUT 
      while(1) {

	// select() on stdin and dgaf about keystrokes
	select(0, NULL, NULL, NULL, &parent_timeout);
	if(parent_timeout.tv_usec == 0)
	  break;
      }

      // Check for Ctrl+C
      if(interrupt_flag) {
	fprintf(stderr,
	    "Packette (parent): Received SIGINT, waiting for children to finish...\n");
	break;
      }

      // Reset the output buffer position for sprintf
      output[0] = 0;

      // Reset the running totals
      total_kpps = 0.0;
      total_MBps = 0.0;
      total_Mp = 0.0;
      total_MB = 0.0;

      for(k = 0; k < children; ++k) {

	// Make some volatile pointers into shared memory
	packets_processed_ptr = (unsigned long *)scratchpad + 2*k;
	bytes_processed_ptr = (unsigned long *)scratchpad + 2*k + 1;

	// Pull values from the volatile locations once
	packets_processed = *packets_processed_ptr;
	bytes_processed = *bytes_processed_ptr;
	
	// XXX Clearly not safe
	// packets always 33 wide
	sprintf(output,
		"%s%6.d | %9.3f kpps (%9.3fMBps) | %7.3f Mp (%7.3fMB)\n",
		output,
		kids[k],
		1000.0*(packets_processed - previous_processed[2*k])/REFRESH_PERIOD,
		1.0*(bytes_processed - previous_processed[2*k + 1])/REFRESH_PERIOD,
		packets_processed/1e6,
		bytes_processed/1e6);

	// Add totals
	total_kpps += 1000.0*(packets_processed - previous_processed[2*k])/REFRESH_PERIOD;
	total_MBps += 1.0*(bytes_processed - previous_processed[2*k + 1])/REFRESH_PERIOD;
	
	total_Mp += packets_processed/1.0e6;
	total_MB += bytes_processed/1.0e6;
	
	// Store for computation of instantaneous performances
	previous_processed[2*k] = packets_processed;
	previous_processed[2*k + 1] = bytes_processed;
      }
      
      // Add in the totals
      sprintf(output,
	      "%s-----------------------------------------------------------------\n", output);

      sprintf(output,
	      "%s Total | %9.3f kpps (%9.3fMBps) | %7.3f Mp (%7.3fMB)\n\n",
	      output,
	      total_kpps,
	      total_MBps,
	      total_Mp,
	      total_MB);

      // ncurses output?
      if(ordered_file != stdout) {
	mvprintw(11,0,output);
	mvprintw(15,0,"Press Ctrl+C when you've had your fill...");
	refresh();
      }
      else
	fprintf(stderr, output);
    }

    // Close ncurses?
    if(ordered_file != stdout)
      endwin();
    
    // Wait for the children to finish up
    k = children;
    while(k--) {
      waitpid(kids[k], &retval, 0);
      fprintf(stderr,
	      "Packette (parent): child-%d (PID %d) has completed\n",
	      k,
	      kids[k]);
    }

    // Unmap the shared memory
    if(munmap(scratchpad, children*sizeof(unsigned long)*2)) {

      perror("munmap()");
      exit(EXIT_FAILURE);
    }

    fprintf(stderr, "Packette (parent): Deallocated shared memory scratchpad.\n");
    
    // Unnecessary Cleanup
    free(previous_processed);
    free(kids);
    exit(0);
  }
  
  // Even though this will get torn down on process completion,
  // come correct.
  //  cleanup();
}   
