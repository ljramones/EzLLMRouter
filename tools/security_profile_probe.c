#define _GNU_SOURCE
#include <dlfcn.h>
#include <locale.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>

static int outside = 0;
static int readonly_guard = 0;
static void *guard = NULL;
static void *check_thread(void *unused) {
    (void)unused;
    pthread_attr_t attributes;
    void *stack = NULL;
    size_t size = 0;
    if (pthread_getattr_np(pthread_self(), &attributes) != 0) return NULL;
    if (pthread_attr_getstack(&attributes, &stack, &size) != 0) return NULL;
    uintptr_t address = (uintptr_t)dlsym(RTLD_DEFAULT, "__stack_chk_guard");
    outside = address && (void *)address == guard
        && !(address >= (uintptr_t)stack && address < (uintptr_t)stack + size);
    pthread_attr_destroy(&attributes);
    return NULL;
}
int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--identity") == 0) {
        printf("{\"uid\":%lu,\"euid\":%lu,\"no_new_privs\":%d}\n",
            (unsigned long)getuid(), (unsigned long)geteuid(), prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0));
        return 0;
    }
    guard = dlsym(RTLD_DEFAULT, "__stack_chk_guard");
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return 2;
    char line[2048];
    while (fgets(line, sizeof(line), maps)) {
        unsigned long first, last;
        char modes[5] = {0};
        if (sscanf(line, "%lx-%lx %4s", &first, &last, modes) == 3
            && (uintptr_t)guard >= first && (uintptr_t)guard < last)
            readonly_guard = modes[0] == 'r' && modes[1] != 'w';
    }
    fclose(maps);
    pthread_t thread;
    if (pthread_create(&thread, NULL, check_thread, NULL) != 0) return 3;
    if (pthread_join(thread, NULL) != 0) return 4;
    const char *locale = setlocale(LC_ALL, "");
    printf("{\"uid\":%lu,\"euid\":%lu,\"no_new_privs\":%d,"
        "\"guard_global\":%s,\"guard_outside_thread_stack\":%s,\"guard_readonly\":%s,"
        "\"locale\":\"%s\"}\n", (unsigned long)getuid(), (unsigned long)geteuid(),
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0), guard ? "true" : "false",
        outside ? "true" : "false", readonly_guard ? "true" : "false", locale ? locale : "");
    return 0;
}
