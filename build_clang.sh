#!/bin/bash
set -e
CLION_BASE=/data00/home/guohuanwei.cztj/.local/share/JetBrains/Toolbox/apps/clion/bin
CMAKE=$CLION_BASE/cmake/linux/x64/bin/cmake
NINJA_DIR=$CLION_BASE/ninja/linux/x64
export PATH=/usr/bin:$NINJA_DIR:$PATH

cd /data00/home/guohuanwei.cztj/git_files/trade

echo "=== CMake Configure ==="
$CMAKE --preset linux-clang 2>&1

echo "=== Build ==="
$CMAKE --build --preset linux-clang -j$(nproc) 2>&1
