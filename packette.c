#define _GNU_SOURCE

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

// Local stuff
#include "packette.h"

#define DEBUG

///////////////////////////// GLOBALS /////////////////////////

// Note that things are unsigned long because we want to avoid implicit casts
// during computation.
void (*process_packets_fptr)(void *buf, int vlen, FILE *ordered_file, FILE *orphan_file);

unsigned long *emptyBlock;

// This is used to signal that we should cleanup
volatile sig_atomic_t interrupt_flag = 0;

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
// Everytime we push to the stream
//

//
// PACKET PROCESSORS
//
void super_nop_processor(void *buf, int vlen, FILE *ordered_file, FILE *orphan_file) {

  //
  // Writes the entire message buffer at once, including deadspace not necessarily
  // consumed by the packets.
  //
  fwrite(buf,
	 BUFSIZE,
	 vlen,
	 ordered_file);
}

void nop_processor(void *buf, int vlen, FILE *ordered_file, FILE *orphan_file) {

  struct packette_transport *ptr;
  
  //
  // This does nothing but write packet headers and payloads to the ordered file.
  // (This removes buffer garbage)
  //
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // Blast
    fwrite(buf,
	   sizeof(struct packette_transport) + ptr->channel.num_samples * SAMPLE_WIDTH,
	   1,
	   ordered_file);

    // Get the next one
    buf += BUFSIZE;
  }
}

void debug_processor(void *buf, int vlen, FILE *ordered_file, FILE *orphan_file) {

  struct packette_transport *ptr;
  
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
    "RESERVED:\t\t\t0x%.2x 0x%.2x 0x%.2x\n"
    "Channel number:\t\t\t%u\n"
    "Total samples (all fragments):\t%u\n"
    "DRS4 stop:\t\t\t%u\n\n";
  
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
	    ((unsigned char *)&(ptr->header.channel_mask))[7], ((unsigned char *)&(ptr->header.channel_mask))[6],
	    ((unsigned char *)&(ptr->header.channel_mask))[5], ((unsigned char *)&(ptr->header.channel_mask))[4],
	    ((unsigned char *)&(ptr->header.channel_mask))[3], ((unsigned char *)&(ptr->header.channel_mask))[2],
	    ((unsigned char *)&(ptr->header.channel_mask))[1], ((unsigned char *)&(ptr->header.channel_mask))[0],
	    ptr->channel.reserved[0], ptr->channel.reserved[1], ptr->channel.reserved[2],
	    ptr->channel.channel,
	    ptr->channel.num_samples,
	    ptr->channel.drs4_stop);
    
    // Get the next one
    buf += BUFSIZE;
  }
}

//
// Called when the child receives SIGINT
//
void flushChild(int signum) {

  // This is a special volatile signal-safe integer type:
  //  https://wiki.sei.cmu.edu/confluence/display/c/SIG31-C.+Do+not+access+shared+objects+in+signal+handlers
  interrupt_flag = 1;
}

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

  // Argument parsing stuff
  int flags, opt;
  int nsecs, tfnd;
  unsigned short port;
  char *addr_str;

  // Signal handling stuff
  struct sigaction new_action, old_action;

  // Files and data output stuff
  FILE *ordered_file;            // Stage I reconstruction (ordered and stripped) output
  FILE *orphan_file;               // Stage II reconstruction (unordered, raw) output
  struct tm lt;            // For holding time stuff
  time_t secs;
  char tmp1[1024], tmp2[1024];
  
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

    // Install signal handler so we cleanly flush packets
    // From GNU docs:
    //  https://www.gnu.org/software/libc/manual/html_node/Sigaction-Function-Example.html
    new_action.sa_handler = &flushChild;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    ////////////////// STREAMS //////////////////
    
    	    
    // Open streams for output
    if(!ordered_file) {
      
      sprintf(tmp2, "%s_%s_%d.ordered", tmp1, addr_str, port);
      if( ! (ordered_file = fopen(tmp2, "wb"))) {
	perror("fopen()");
	exit(EXIT_FAILURE);
      }
    }
    
    sprintf(tmp2, "%s_%s_%d.orphans", tmp1, addr_str, port);
    
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
	    port);
        
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
    // We read in directly to payload buffers
    memset(msgs, 0, sizeof(struct mmsghdr) * vlen);
    
    // Set this up to directly transfer payloads
    for (i = 0; i < vlen; i++) {
      iovecs[i].iov_base         = buf + i*(BUFSIZE);         // This should be a correctly operating pointer arithmetic...
      iovecs[i].iov_len          = BUFSIZE;
      msgs[i].msg_hdr.msg_iov    = &iovecs[i];
      msgs[i].msg_hdr.msg_iovlen = 1;
    }

    timeout.tv_sec = TIMEOUT;
    timeout.tv_nsec = 0;

    // Now pull packets in bulk
    // Pull as many as will fit in L2 cache on your platform
    while(1) {

      // Try to grab at most vlen packets, timing out after TIMEOUT
      retval = recvmmsg(sockfd, msgs, vlen, 0, &timeout);

#ifdef DEBUG
      fprintf(stderr,
	      "Packette (PID %d): Received %d packets.\n",
	      pid,
	      retval);
#endif
      
      // Process only the packets received
      if (retval > 0)
	(*process_packets_fptr)(buf, retval, ordered_file, orphan_file);
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

    // Block SIGINT
    sigemptyset (&new_action.sa_mask);
    new_action.sa_handler = SIG_IGN;
    sigaction(SIGINT, &new_action, NULL);

    fprintf(stderr,
	    "Packette (parent): waiting for children to finish...\n");
    
	    
    k = children;
    while(k--) {
      waitpid(kids[k], &retval, 0);
      fprintf(stderr,
	      "Packette (parent): child-%d (PID %d) has completed\n",
	      k,
	      kids[k]);
    }
    
    exit(0);
  }
  
  // Even though this will get torn down on process completion,
  // come correct.
  free(kids);
  //  cleanup();
}   
