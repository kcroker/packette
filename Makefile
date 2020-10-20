CFLAG = -Wall -g

packette:packette.c
	gcc ${CFLAGS} -o $@ $^ -lncurses

packette_merge: packette_merge.c
	gcc ${CFLAGS} -o $@ $^

all: packette packette_merge

clean:
	rm -f *.o

