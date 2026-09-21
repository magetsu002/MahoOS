#ifndef MAHO_PREVENTION_SHARED_H
#define MAHO_PREVENTION_SHARED_H

#include <linux/types.h>

#define MAHO_SCOPE_RECURSIVE (1U << 0)

#define MAHO_OP_WRITE   (1ULL << 0)
#define MAHO_OP_CREATE  (1ULL << 1)
#define MAHO_OP_UNLINK  (1ULL << 2)
#define MAHO_OP_RENAME  (1ULL << 3)
#define MAHO_OP_LINK    (1ULL << 4)
#define MAHO_OP_SYMLINK (1ULL << 5)
#define MAHO_OP_SETATTR (1ULL << 6)
#define MAHO_OP_MOUNT   (1ULL << 7)
#define MAHO_OP_DEVICE  (1ULL << 8)

struct maho_object_key {
    __u64 dev;
    __u64 ino;
};

struct maho_protected_value {
    __u64 effect_mask;
    __u32 flags;
    __u32 reserved;
};

struct maho_authority_key {
    __u32 tgid;
    __u32 reserved;
    __u64 start_ticks;
    __u64 executable_dev;
    __u64 executable_ino;
    __u64 scope_dev;
    __u64 scope_ino;
};

struct maho_authority_value {
    __u64 expires_boot_ns;
    __u64 effect_mask;
    __u64 operation_mask;
    __u64 transaction_tag;
};

struct maho_prevention_event {
    __u64 timestamp_ns;
    __u64 target_dev;
    __u64 target_ino;
    __u64 scope_dev;
    __u64 scope_ino;
    __u64 effect_mask;
    __u64 operation_mask;
    __u64 subject_start_ticks;
    __u64 executable_dev;
    __u64 executable_ino;
    __u32 tgid;
    __u32 uid;
    __s32 result;
    __u32 authority_state;
};

#endif
