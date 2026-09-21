// SPDX-License-Identifier: GPL-2.0
#define _GNU_SOURCE
#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "../bpf/maho_prevention_shared.h"

static int mkdir_one(const char *path)
{
    if (mkdir(path, 0700) == 0 || errno == EEXIST)
        return 0;
    perror(path);
    return -1;
}

static int add_scope(int map_fd, int device_map_fd, const char *spec)
{
    char *copy = strdup(spec), *effect_text, *recursive_text, *path;
    char *save = NULL;
    struct stat st;
    struct maho_object_key key;
    struct maho_protected_value value;
    unsigned long long effect;
    int result = -1;
    if (!copy)
        return -1;
    effect_text = strtok_r(copy, ":", &save);
    recursive_text = strtok_r(NULL, ":", &save);
    path = strtok_r(NULL, "", &save);
    if (!effect_text || !recursive_text || !path || path[0] != '/') {
        fprintf(stderr, "invalid scope specification: %s\n", spec);
        goto out;
    }
    effect = strtoull(effect_text, NULL, 0);
    if (!effect || (strcmp(recursive_text, "0") && strcmp(recursive_text, "1"))) {
        fprintf(stderr, "invalid scope effect/flags: %s\n", spec);
        goto out;
    }
    if (stat(path, &st) != 0) {
        fprintf(stderr, "scope target unavailable: %s: %s\n", path, strerror(errno));
        goto out;
    }
    key.dev = st.st_dev;
    key.ino = st.st_ino;
    value.effect_mask = effect;
    value.flags = !strcmp(recursive_text, "1") ? MAHO_SCOPE_RECURSIVE : 0;
    value.reserved = 0;
    if (bpf_map_update_elem(map_fd, &key, &value, BPF_NOEXIST) != 0 && errno != EEXIST) {
        fprintf(stderr, "cannot protect %s: %s\n", path, strerror(errno));
        goto out;
    }
    if (S_ISBLK(st.st_mode)) {
        /* struct inode.i_rdev uses the kernel's 12:20 dev_t encoding. */
        __u64 device = ((__u64)major(st.st_rdev) << 20) | minor(st.st_rdev);
        if (bpf_map_update_elem(device_map_fd, &device, &value, BPF_ANY) != 0) {
            fprintf(stderr, "cannot protect block device %s: %s\n", path, strerror(errno));
            goto out;
        }
    }
    result = 0;
out:
    free(copy);
    return result;
}

int main(int argc, char **argv)
{
    struct bpf_object *object = NULL;
    struct bpf_program *program;
    struct bpf_link *links[64] = {};
    size_t link_count = 0;
    char maps_dir[PATH_MAX], links_dir[PATH_MAX];
    int protected_fd, device_fd, state_fd, error = 1;
    __u32 state_key = 0, inactive = 0, active = 1;

    if (argc < 5 || strcmp(argv[1], "load")) {
        fprintf(stderr, "usage: %s load OBJECT PIN_ROOT EFFECT:RECURSIVE:/path [...]\n", argv[0]);
        return 2;
    }
    libbpf_set_strict_mode(LIBBPF_STRICT_ALL);
    object = bpf_object__open_file(argv[2], NULL);
    if (libbpf_get_error(object)) {
        fprintf(stderr, "cannot open BPF object: %s\n", strerror(-libbpf_get_error(object)));
        object = NULL;
        goto out;
    }
    if (bpf_object__load(object)) {
        fprintf(stderr, "kernel rejected Maho prevention BPF object\n");
        goto out;
    }
    snprintf(maps_dir, sizeof(maps_dir), "%s/maps", argv[3]);
    snprintf(links_dir, sizeof(links_dir), "%s/links", argv[3]);
    if (mkdir_one(argv[3]) || mkdir_one(maps_dir) || mkdir_one(links_dir))
        goto out;
    protected_fd = bpf_object__find_map_fd_by_name(object, "protected_objects");
    device_fd = bpf_object__find_map_fd_by_name(object, "protected_devices");
    state_fd = bpf_object__find_map_fd_by_name(object, "enforcement_state");
    if (protected_fd < 0 || device_fd < 0 || state_fd < 0)
        goto out;
    if (bpf_map_update_elem(state_fd, &state_key, &inactive, BPF_ANY))
        goto out;
    for (int index = 4; index < argc; index++)
        if (add_scope(protected_fd, device_fd, argv[index]))
            goto out;
    if (bpf_object__pin_maps(object, maps_dir)) {
        fprintf(stderr, "cannot pin prevention maps: %s\n", strerror(errno));
        goto out;
    }
    bpf_object__for_each_program(program, object) {
        const char *name = bpf_program__name(program);
        struct bpf_link *link;
        if (link_count >= sizeof(links) / sizeof(links[0]))
            goto out;
        link = bpf_program__attach(program);
        if (libbpf_get_error(link)) {
            fprintf(stderr, "cannot attach %s: %s\n", name, strerror(-libbpf_get_error(link)));
            goto out;
        }
        links[link_count++] = link;
        char *link_path = NULL;
        if (asprintf(&link_path, "%s/%s", links_dir, name) < 0)
            goto out;
        if (bpf_link__pin(link, link_path)) {
            fprintf(stderr, "cannot pin %s: %s\n", name, strerror(errno));
            free(link_path);
            goto out;
        }
        free(link_path);
    }
    if (bpf_map_update_elem(state_fd, &state_key, &active, BPF_ANY)) {
        fprintf(stderr, "cannot activate prevention policy\n");
        goto out;
    }
    printf("Maho prevention boundary active: %zu kernel hooks\n", link_count);
    error = 0;
out:
    for (size_t index = 0; index < link_count; index++)
        bpf_link__destroy(links[index]);
    bpf_object__close(object);
    return error;
}
