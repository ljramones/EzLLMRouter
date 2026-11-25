#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <gnu/libc-version.h>
#include <malloc.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum { THREADS=8, CHUNKS=32 };
struct sample { uintptr_t pointer, stack, mapping; int main_heap; };
static struct sample samples[THREADS];
static pthread_barrier_t barrier;
static int iterations;
static uint64_t sums[THREADS];

static int mapping(uintptr_t address, uintptr_t *base, int *main_heap) {
    FILE *file=fopen("/proc/self/maps","r");
    if (!file) abort();
    char line[2048];
    int found=0;
    while (fgets(line,sizeof line,file)) {
        unsigned long first,last;
        if (sscanf(line,"%lx-%lx",&first,&last)==2 && address>=first && address<last) {
            found=1;
            if (base) *base=first;
            if (main_heap) *main_heap=strstr(line,"[heap]")!=NULL;
        }
    }
    if (fclose(file)) abort();
    return found;
}

static int heaps(void) {
    char *text=NULL;
    size_t size=0;
    FILE *file=open_memstream(&text,&size);
    if (!file || malloc_info(0,file) || fclose(file)) abort();
    int count=0;
    for (char *p=text; (p=strstr(p,"<heap nr=")); p++) count++;
    free(text);
    return count;
}

static void await_barrier(void) {
    int result=pthread_barrier_wait(&barrier);
    if (result && result!=PTHREAD_BARRIER_SERIAL_THREAD) abort();
}

static void *thread_main(void *argument) {
    size_t index=(size_t)argument;
    pthread_attr_t attr;
    void *stack=NULL;
    size_t stack_size=0;
    if (pthread_getattr_np(pthread_self(),&attr) || pthread_attr_getstack(&attr,&stack,&stack_size)
        || pthread_attr_destroy(&attr)) abort();
    samples[index].stack=(uintptr_t)stack;
    for (int round=0; round<iterations; round++) {
        void *blocks[CHUNKS];
        size_t sizes[CHUNKS];
        for (int i=0; i<CHUNKS; i++) {
            sizes[i]=4096+(size_t)i*16;
            blocks[i]=malloc(sizes[i]);
            if (!blocks[i]) abort();
            memset(blocks[i],(int)(index+1),sizes[i]);
        }
        if (!round) {
            samples[index].pointer=(uintptr_t)blocks[0];
            await_barrier();
            await_barrier();
        }
        for (int i=CHUNKS-1; i>=0; i--) {
            unsigned char *bytes=blocks[i];
            if (bytes[0]!=index+1 || bytes[sizes[i]-1]!=index+1) abort();
            sums[index]+=bytes[0]+bytes[sizes[i]-1];
            free(blocks[i]);
        }
    }
    return NULL;
}

static int parallel(int rounds, int stress) {
    iterations=rounds;
    pthread_t threads[THREADS];
    pthread_attr_t attr;
    if (pthread_attr_init(&attr) || pthread_attr_setstacksize(&attr,512*1024)
        || pthread_barrier_init(&barrier,NULL,THREADS+1)) abort();
    struct timespec first,last;
    if (clock_gettime(CLOCK_MONOTONIC,&first)) abort();
    for (size_t i=0; i<THREADS; i++)
        if (pthread_create(threads+i,&attr,thread_main,(void *)i)) abort();
    if (pthread_attr_destroy(&attr)) abort();
    await_barrier();
    int arena_count=heaps();
    for (int i=0; i<THREADS; i++)
        if (!mapping(samples[i].pointer,&samples[i].mapping,&samples[i].main_heap)) abort();
    await_barrier();
    for (int i=0; i<THREADS; i++)
        if (pthread_join(threads[i],NULL)) abort();
    if (pthread_barrier_destroy(&barrier) || clock_gettime(CLOCK_MONOTONIC,&last)) abort();
    int retained=0,main_heaps=0;
    for (int i=0; i<THREADS; i++) {
        retained+=mapping(samples[i].stack,NULL,NULL);
        main_heaps+=samples[i].main_heap;
        if (sums[i]!=(uint64_t)rounds*CHUNKS*2*(i+1)) abort();
    }
    Dl_info info;
    if (!dladdr(dlsym(RTLD_DEFAULT,"malloc"),&info)) abort();
    double seconds=(last.tv_sec-first.tv_sec)+(last.tv_nsec-first.tv_nsec)/1e9;
    struct rusage usage;
    if (getrusage(RUSAGE_SELF,&usage)) abort();
    printf("{\"kind\":\"%s\",\"glibc\":\"%s\",\"arenas\":%d,\"threads\":%d,"
           "\"stack_bytes\":524288,\"stacks_retained\":%d,\"thread_allocations_in_brk_heap\":%d,"
           "\"libc_base\":%lu,\"brk\":%lu,\"page_size\":%ld,\"seconds\":%.9f,"
           "\"allocations\":%lu,\"rss_high_water_kib\":%ld,\"integrity\":true,\"mapping_starts\":[",
           stress?"stress":"sample",gnu_get_libc_version(),arena_count,THREADS,retained,main_heaps,
           (unsigned long)info.dli_fbase,(unsigned long)sbrk(0),sysconf(_SC_PAGESIZE),seconds,
           (unsigned long)rounds*THREADS*CHUNKS,usage.ru_maxrss);
    for (int i=0; i<THREADS; i++) printf("%s%lu",i?",":"",(unsigned long)samples[i].mapping);
    printf("]}\n");
    return 0;
}

static int failure(void) {
    FILE *file=fopen("/proc/self/statm","r");
    unsigned long pages;
    if (!file || fscanf(file,"%lu",&pages)!=1 || fclose(file)) abort();
    struct rlimit limit;
    if (getrlimit(RLIMIT_AS,&limit)) abort();
    limit.rlim_cur=(rlim_t)pages*(rlim_t)sysconf(_SC_PAGESIZE)+8*1024*1024;
    if (setrlimit(RLIMIT_AS,&limit)) abort();
    volatile size_t request=256*1024*1024;
    errno=0;
    void *large=malloc(request);
    int rejected=large==NULL && errno==ENOMEM;
    free(large);
    void *small=malloc(128);
    if (!small || !rejected) abort();
    memset(small,0x5a,128);
    free(small);
    printf("{\"kind\":\"failure\",\"enomem\":true,\"small_allocation_survives\":true}\n");
    return 0;
}

static int fallback(void) {
    void *initial=malloc(128);
    if (!initial) abort();
    free(initial);
    size_t page=(size_t)sysconf(_SC_PAGESIZE);
    uintptr_t end=((uintptr_t)sbrk(0)+page-1)&~(page-1);
    void *guard=mmap((void *)end,page,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    if (guard==MAP_FAILED || !mallopt(M_MMAP_MAX,0)) abort();
    void *block=malloc(8*1024*1024);
    int main_heap=0;
    if (!block || !mapping((uintptr_t)block,NULL,&main_heap) || main_heap) abort();
    memset(block,0x5a,8*1024*1024);
    if (((unsigned char *)block)[8*1024*1024-1]!=0x5a) abort();
    int count=heaps();
    free(block);
    if (munmap(guard,page)) abort();
    printf("{\"kind\":\"fallback\",\"brk_extension_blocked\":true,"
           "\"direct_mmap_disabled\":true,\"fallback_allocation_survives\":true,\"arenas\":%d}\n",count);
    return 0;
}

int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"--sample")) return parallel(1,0);
    if (argc==2 && !strcmp(argv[1],"--stress")) return parallel(1000,1);
    if (argc==2 && !strcmp(argv[1],"--failure")) return failure();
    if (argc==2 && !strcmp(argv[1],"--fallback")) return fallback();
    if (argc==2 && !strcmp(argv[1],"--batch")) {
        for (int i=0; i<64; i++) {
            pid_t pid=fork();
            if (pid<0) abort();
            if (!pid) {
                execl("/probe","/probe","--sample",(char *)NULL);
                _exit(127);
            }
            int status;
            if (waitpid(pid,&status,0)!=pid || !WIFEXITED(status) || WEXITSTATUS(status)) return 2;
        }
        return 0;
    }
    return 1;
}
