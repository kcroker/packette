CFLAGS = -Wall -g

.PHONY : all clean packette packette_merge

all: packette #packette_merge

packette:packette.c
	gcc ${CFLAGS} -o $@ $^ -lncurses

packette_merge: packette_merge.c
	gcc ${CFLAGS} -o $@ $^

clean:
	rm packette packette_merge

