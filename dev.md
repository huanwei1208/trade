# at Ubuntu 22.04 
# CMake 3.28+ 
```bash
wget -O - https://apt.kitware.com/keys/kitware-archive-latest.asc 2>/dev/null | gpg --dearmor - | sudo tee /usr/share/keyrings/kitware-archive-keyring.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/kitware-archive-keyring.gpg] https://apt.kitware.com/ubuntu/ jammy main" | sudo tee /etc/apt/sources.list.d/kitware.list >/dev/null
sudo apt-cache policy cmake | grep 3.28
sudo apt install \
    cmake=3.28.6-0kitware1ubuntu22.04.1 \
    cmake-data=3.28.6-0kitware1ubuntu22.04.1
```

# ninja
sudo apt install ninja-build

# clang
sudo apt install clang-13
sudo apt install libc++-13-dev libc++abi-13-dev
# gcc
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt update
sudo apt install gcc-13 g++-13

# dependencies
sudo apt install libomp-13-dev
sudo apt install libssl-dev
sudo apt install libsnappy-dev



---------
# python
mkdir -p data
uv sync

source .venv/bin/activate



------------------

