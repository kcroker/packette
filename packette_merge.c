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

//
// Compares sequence numbers for qsort()
//
int eval_seqnum(const void *a, const void *b) {

  return ((const struct packette_transport *)a)->assembly.seqnum
    < ((const struct packette_transport *)b)->assembly.seqnum;
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

//
// packette_merge is a simpler program designed to be 
// run via xargs
//
// It takes an ordered packette file and an orphan packette file
// and merges them into a single file that is ordered in
// sequence number.
//
// 1) The orphan file is qsort()ed
// 2) The ordered file is written to filename.merged one
//    transport packet at a time until a jump in sequence
//    number is detected.  Packets are pulled from the
//    sorted orphan file until the sequence is patched
//    or there are no more events.
// 3) 
int main(int argc, char **argv) {

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
  FILE *merged_file;               // Merged output

  // General purpose string buffers
  char tmp1[1024], tmp2[1024];

  // Initialization
  tmp1[0] = 0x0;
  merged_file = 0x0;
  
  /////////////////// ARGUMENT PARSING //////////////////
  
  while ((opt = getopt(argc, argv, "o")) != -1) {
    switch (opt) {
    case 'o':
      merged_file = stdout;
      break;
    default: /* '?' */
      fprintf(stderr, "Usage: %s [-o dump to standard out] FILE_PREFIX\n",	argv[0]);
      exit(EXIT_FAILURE);
    }
  }

  // Sanity check
  if(merged_file)
    fprintf(stderr, "Packette_merge: dumping to stdout...\n");

  // Now grab mandatory positional arguments
  if(optind >= argc) {
    fprintf(stderr, "Expected file prefix\n");
    exit(EXIT_FAILURE);
  }

  // For clarity
  prefix_str = argv[optind];

  // Attempt to open the prefix files
  sprintf(tmp1, "%s.orphans", prefix_str);

  // Open the orphansfile
  if(! (orphan_file = fopen(tmp, "rb"))) {
    perror("fopen()");
    exit(EXIT_FAILURE);
  }

  // Make sure there are some orphans
  fseek(orphan_file, 0, SEEK_END);

  // How big is it?
  orphan_size = ftell(orphan_file);

  // Was it empty?
  if(!orphan_size) {
    fprintf(stderr,
	    "SUCESS: Attempted to merge an empty orphan file.  Congratulations, you received everything in order.\n");
    exit(0);
  }

  // Is it corrupted?
  if(orphan_size % BUFSIZE) {
    fprintf(stderr,
	    "ERROR: Orphans file is not the correct length and qsort() will fail.  Corruption likely, but perhaps not terminal.  Walk the file yourself if you really need it.");
    exit(EXIT_FAILURE);
  }

  // Attempt to allocate memory large enough to
  // sort the orphans in place
  if(! (orphans = malloc(orphan_size))) {
    perror("malloc()");
    fprintf(stderr,
	    "ERROR: Failed to allocate %d bytes for in-place sort of orphans.  Your orphan file should not be gigabytes...");
    exit(EXIT_FAILURE);
  }

  // Go back to the beginning and load the stream
  fseek(orphan_file, 0, SEEK_START);
  fread(buf,
	BUFSIZE,
	orphan_size / BUFSIZE,
	orphan_file);

  // Check for weird errors that should not happen at this point
  if(!feof() || ferror()) {
    perror("fread()");
    fprintf(stderr,
	    "Here be dragons");
    exit(EXIT_FAILURE);
  }

  // Close the file
  fclose(orphan_file);
  
  //
  // Step 1)
  //
  // qsort() the orphans
  //
  fprintf(stderr,
	  "Packette_merge: sorting %d orphan events...", orphan_size / BUFSIZE);
  qsort(orphans, orphan_size / BUFSIZE, BUFSIZE, eval_seqnum);
  fprintf(stderr,
	  "Packette_merge: sorting complete.");

  //
  // Step 2)
  //
  // Process the ordered stream and output streams in serial
  // so we keep memory usage as low as possible
  //

  // Attempt to open the ordered and merged files
  sprintf(tmp1, "%s.ordered", prefix_str);
  if(! (ordered_file = fopen(tmp1, "rb"))) {
    perror("fopen()");
    exit(EXIT_FAILURE);
  }

  sprintf(tmp1, "%s.merged", prefix_str);
  if(! (merged_file = fopen(tmp1, "rb"))) {
    perror("fopen()");
    exit(EXIT_FAILURE);
  }

  // Allocate a buffer
  if(! (ordered = malloc(BUFSIZE))) {
    perror("malloc()");
    exit(EXIT_FAILURE);
  }

  // Report what we've been asked to do
  fprintf(stderr,
	  "Packette-merge: will do an ordered merge of packette files with prefix %s\n", prefix_str);
  
  // Catch Ctrl+C so we don't (easily) write corrupted output.
  new_action.sa_handler = &flagInterrupt;
  sigemptyset (&new_action.sa_mask);
  new_action.sa_flags = 0;

  sigaction(SIGINT, NULL, &old_action);
  if (old_action.sa_handler != SIG_IGN)
    sigaction(SIGINT, &new_action, NULL);

  // Perform the merge
  while(1) {

    // Grab an ordered block header
    fread(ordered,
	  sizeof(struct packette_transport),
	  1,
	  ordered_file);

    // Did we successfully read
    if(!feof(ordered_file) && !ferror(ordered_file)) {

      // Get caught up
      while(eval_seqnum(ordered, ptr) > 0) {

	fprintf(stderr,
		"Packette_merge: placing orphan %u\n",
		(struct packette_transport *)ptr->assembly.seqnum);
	
	// Write the orphan, ignoring excess buffer space
	fwrite(ptr,
	       sizeof(struct packette_transport) + (struct packette_transport *)ptr->channel.num_samples*SAMPLE_WIDTH,
	       1,
	       merged_file);

	// Go to the next one
	ptr += BUFSIZE;
      }

      // Get the remainder of this ordered packet
      fread(ordered + sizeof(struct packette_transport),
	    (struct packette_transport *)ordered->channel.num_samples*SAMPLE_WIDTH,
	    1,
	    ordered_file);
	    
      // Write out the entire ordered packet to merged
      fwrite(ordered,
	     sizeof(struct packette_transport) + (struct packette_transport *)ordered->channel.num_samples*SAMPLE_WIDTH,
	     1,
	     merged_file);

      // Duplicates will never happen, because we drop them in stage I.      
    }
    else {

      // Did we encounter an error?
      if(ferror(ordered_file)) {

	perror("fread()");
	fprintf(stderr,
	      "WARNING: error encountered on reading ordered file.  Trying to end gracefully...\n");
	break;
      }

      // We must be done.
      fprintf(stderr,
	      "Packette_merge: Finished processing all ordered fragments.\n");

      //
      // Check some edge cases...
      //
      
      // Write out all the remaining orphans
      // (this shouldn't happen?)
      while(ptr - orhpans < orphan_size) {

	fprintf(stderr,
	      "WARNING: orphans with sequence number greater than the last ordered fragment exist.  This should not happen?\n");

	fwrite(ptr,
	       sizeof(struct packette_transport) + (struct packette_ptr *)ptr->channel.num_samples*SAMPLE_WIDTH,
	       1,
	       ordered_file);

	ptr += BUFSIZE;
      }

      fprintf(stderr,
	      "Packette_merge: Wrote any remaining orphans at end of ordered list.\n");
    }

    // Look for Ctrl+C
    if(interrupt_flag) {

      // Finish up and close
      fprintf(stderr,
	      "Packette_merge: Caught Ctrl+C, cleaning up....\n");
      break;
    }
  }

  // Close streams
  fclose(merged_stream);
  fclose(ordered_stream);

  // Clean up
  free(buf);
  free(orphans);

  // Done.
  fprintf(stderr,
	  "Packette_merge: Done.\n");
}
