### these are the commands that are executed to run unit tests for a given project ###

unittest_commands = {
    "serenity": "mkdir -p build && cd build && cmake -GNinja -DBUILD_LAGOM=ON .. && ninja && ctest -j$(nproc) \n\
    LOG_FILE=\\\"/src/serenity/Meta/Lagom/build/Testing/Temporary/LastTest.log\\\"\n\
    if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
      echo \\\"\\n========== Test Log Output ==========\\\"\n\
      cat \\\"\\$LOG_FILE\\\"\n\
      echo \\\"\\n========== End of Test Log ==========\\\"\n\
    else\n\
      echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
    fi\n",
    "gdal": "apt update && apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev wget \n\
    cd /src && wget https://www.python.org/ftp/python/3.7.4/Python-3.7.4.tgz \n\
    tar xzf Python-3.7.4.tgz && cd Python-3.7.4 && ./configure && make -j\\$(nproc) && make install \n \
    update-alternatives --install /usr/bin/python python /usr/local/bin/python3.7 50 && \
    update-alternatives --set python /usr/local/bin/python3.7 \n \
    cd /src && sed -i \
    -e 's|./configure --disable-shared|./configure --enable-shared  --disable-static|g' \
    -e 's|./configure --without-libtool|./configure --enable-shared  --disable-static --without-libtool|g' \
    -e 's|-DHDF5_C_LIBRARY=libhdf5_serial.a|-DHDF5_C_LIBRARY=libhdf5_serial.so|g' \
    -e 's|-DHDF5_HL_LIBRARY=libhdf5_serial_hl.a|-DHDF5_HL_LIBRARY=libhdf5_serial_hl.so|g' \
    -e 's|-DBUILD_SHARED_LIBS:BOOL=OFF|-DBUILD_SHARED_LIBS:BOOL=ON|g' \
    -e 's|export LDFLAGS=\\${CXXFLAGS}|export LDFLAGS=\\\"\\$CXXFLAGS\\\"|g' \
    -e '\\|make -j\\$(nproc) -s static-lib|q' \
    build.sh \n \
    sed -i 's|make -j\\$(nproc) -s static-lib|make -j\\$(nproc) -s|g' build.sh \n \
    echo \\\"make install\\\" >> build.sh \n \
    cd /src/gdal && ../build.sh \n \
    export CPPFLAGS=\\\"-I/src/gdal/gdal/port -I/src/gdal/gdal/gcore -I/src/gdal/gdal/alg -I/src/gdal/gdal/ogr -I/src/gdal/gdal/ogr/ogrsf_frmts -I/src/gdal/gdal/gnm -I/src/gdal/gdal/apps\\\" \n\
    cd /src/gdal/gdal/swig/python && pip3 install . && pip3 install numpy pytest setuptools wheel \n\
    export LD_LIBRARY_PATH=/usr/local/lib:\\\"\\$LD_LIBRARY_PATH\\\" \n \
    echo \\\"/src/install/lib\\\" > /etc/ld.so.conf.d/gdal-proj.conf \n \
    ldconfig \n \
    cd /src/gdal/autotest && PYTEST_ADDOPTS=\\\"-vv -rA --tb=short --show-capture=all\\\" timeout --preserve-status 20m make -j test",  # for gdal, we only run 20 min since the rest tests are irrelevant

    "kimageformats": "apt-get update\n\
    apt-get install -y build-essential libssl-dev wget software-properties-common ca-certificates\n\
    export CFLAGS=\\\"\\$(echo \\$CFLAGS | sed 's/-gline-tables-only//')\\\" && export CXXFLAGS=\\\"\\$(echo \\$CXXFLAGS | sed 's/-gline-tables-only//' -e 's/-stdlib=libc++//')\\\"\n\
    cd /src && wget https://cmake.org/files/v3.7/cmake-3.7.2.tar.gz && tar -zxvf cmake-3.7.2.tar.gz && cd cmake-3.7.2 && ./bootstrap \n\
    make -j\\$(nproc) && make install\n\
    add-apt-repository -y ppa:savoury1/kde-5-80 && apt-get update && apt-get install -y extra-cmake-modules\n\
    cd \\$SRC/qtbase\n\
    sed -i -e \\\"s/QMAKE_CXXFLAGS    += -stdlib=libc++/QMAKE_CXXFLAGS    += -stdlib=libc++  \\$CXXFLAGS/g\\\" mkspecs/linux-clang-libc++/qmake.conf\n\
    sed -i -e \\\"s/QMAKE_LFLAGS      += -stdlib=libc++/QMAKE_LFLAGS      += -stdlib=libc++ -lpthread \\$CXXFLAGS/g\\\" mkspecs/linux-clang-libc++/qmake.conf\n\
    sed -i -e \\\"s/MAKE\\\\\\\")/MAKE\\\\\\\" -j10)/g\\\" configure\n\
    sed -i -e \\\"s/DEFINES += QT_RCC QT_NO_CAST_FROM_ASCII QT_NO_FOREACH/DEFINES += QT_NO_COMPRESS QT_RCC QT_NO_CAST_FROM_ASCII QT_NO_FOREACH/g\\\" src/tools/rcc/rcc.pro\n\
    ./configure --glib=no --libpng=qt -opensource -confirm-license -no-opengl -no-icu -platform linux-clang-libc++ -v\n\
    cd src\n\
    ../bin/qmake -o Makefile src.pro\n\
    make sub-gui -j\\$(nproc)\n\
    cd \\$SRC/kimageformats\n\
    mkdir build && cd build\n\
    cmake .. -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_PREFIX_PATH=\\\"\\$SRC/qtbase;/usr/local\\\" -DCMAKE_DISABLE_FIND_PACKAGE_KF5Archive=ON -DCMAKE_DISABLE_FIND_PACKAGE_OpenEXR=ON -DCMAKE_DISABLE_FIND_PACKAGE_Qt5PrintSupport=ON -DQt5Core_DIR=\\\"\\$SRC/qtbase/lib/cmake/Qt5Core\\\" -DQt5Gui_DIR=\\\"\\$SRC/qtbase/lib/cmake/Qt5Gui\\\" -DQt5Test_DIR=\\\"\\$SRC/qtbase/lib/cmake/Qt5Test\\\"\n\
    make -j\\$(nproc) && ctest \n\
    LOG_FILE=\\\"/src/kimageformats/build/Testing/Temporary/LastTest.log\\\"\n\
    if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
      echo \\\"\\n========== Test Log Output ==========\\\"\n\
      cat \\\"\\$LOG_FILE\\\"\n\
      echo \\\"\\n========== End of Test Log ==========\\\"\n\
    else\n\
      echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
    fi\n",

    "wasm3": "vulpatch compile && cd /src/wasm3/test && \n\
echo \\\"Initializing test suite (downloading if needed)...\\\"\n\
python3 ./run-spec-test.py\n\
\n\
TEST_FILES=\\$(find .spec-* -name '*.json')\n\
\n\
for test_file in \\$TEST_FILES; do\n\
  echo \\\"\\n========== Running \\$test_file ==========\\\"\n\
  python3 ./run-spec-test.py \\\"\\$test_file\\\" --show-logs --verbose\n\
  echo \\\"\\n========================================\\n\\\"\n\
done\n",

    "pcre2": "vulpatch compile && make check ; cat ./test-suite.log",
    "arrow": "apt update && apt install -y python libstdc++-5-dev libboost-dev libboost-system-dev libboost-filesystem-dev libboost-regex-dev || true &&\
    cd /work && rm -rf * && export ASAN_OPTIONS=\\\"detect_leaks=0\\\" && \
    export CFLAGS=\\\"\\$(echo \\$CFLAGS | sed 's/-gline-tables-only//')\\\" && export CXXFLAGS=\\\"\\$(echo \\$CXXFLAGS | sed 's/-gline-tables-only//' -e 's/-stdlib=libc++//')\\\" && \
    cmake /src/arrow/cpp -DCMAKE_BUILD_TYPE=Release     -DARROW_DEPENDENCY_SOURCE=BUNDLED     -DBOOST_SOURCE=SYSTEM     \
    -DCMAKE_C_FLAGS=\\\"\\$CFLAGS\\\"     -DCMAKE_CXX_FLAGS=\\\"\\$CXXFLAGS\\\"     -DARROW_EXTRA_ERROR_CONTEXT=off     -DARROW_JEMALLOC=off    \
    -DARROW_MIMALLOC=off     -DARROW_FILESYSTEM=off     -DARROW_PARQUET=on     -DARROW_BUILD_SHARED=off     -DARROW_BUILD_STATIC=on    \
    -DARROW_BUILD_TESTS=on     -DARROW_BUILD_INTEGRATION=off     -DARROW_BUILD_BENCHMARKS=off     -DARROW_BUILD_EXAMPLES=off     \
    -DARROW_BUILD_UTILITIES=off     -DARROW_TEST_LINKAGE=static     -DPARQUET_BUILD_EXAMPLES=off     -DPARQUET_BUILD_EXECUTABLES=off    \
    -DPARQUET_REQUIRE_ENCRYPTION=off     -DARROW_WITH_BROTLI=on     -DARROW_WITH_BZ2=off     -DARROW_WITH_LZ4=off     -DARROW_WITH_SNAPPY=off    \
    -DARROW_WITH_ZLIB=off     -DARROW_WITH_ZSTD=off     -DARROW_USE_GLOG=off   -DARROW_PARQUET=off  -DARROW_USE_ASAN=off     -DARROW_USE_UBSAN=off     -DARROW_USE_TSAN=off   \
    -DARROW_FUZZING=off && make -j\\$(nproc) && make unittest\n\
    LOG_FILE=\\\"/work/Testing/Temporary/LastTest.log\\\"\n\
    if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
      echo \\\"\\n========== Test Log Output ==========\\\"\n\
      cat \\\"\\$LOG_FILE\\\"\n\
      echo \\\"\\n========== End of Test Log ==========\\\"\n\
    else\n\
      echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
    fi\n",
    "yara": "cd \\$GIT_DIR && source ../build.sh && make check",
    "openexr": "cd /work && \
        cmake /src/openexr -D BUILD_TESTING=ON -D OPENEXR_INSTALL_EXAMPLES=OFF -D OPENEXR_RUN_FUZZ_TESTS=OFF && \
        make OpenEXRCore && \
        make OpenEXRCoreTest/fast && \
        ctest -R 'OpenEXRCore\\..+' 10\n\
  LOG_FILE=\\\"/work/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "rdkit": "apt-get update && apt-get install -y build-essential cmake python3-dev python3-numpy libboost-all-dev libeigen3-dev flex bison zlib1g-dev\n\
  export RDBASE=/src/rdkit\n\
  sed -i '/add_executable(gaExample/,+4 s/^/#/' /src/rdkit/Code/GraphMol/RGroupDecomposition/CMakeLists.txt\n\
  rm -rf build && mkdir build && cd build && \\\n\
    cmake .. -DRDK_BUILD_PYTHON_WRAPPERS=OFF -DRDK_BUILD_SWIG_WRAPPERS=OFF -DRDK_BUILD_FREETYPE_SUPPORT=OFF -DRDK_BUILD_CAIRO_SUPPORT=OFF -DRDK_BUILD_COORDGEN_SUPPORT=OFF -DRDK_BUILD_AVALON_SUPPORT=OFF -DRDK_BUILD_INCHI_SUPPORT=OFF -DRDK_BUILD_CPP_TESTS=ON -DRDK_USE_BOOST_SERIALIZATION=OFF -DRDK_USE_FLEXBISON=ON && \\\n\
    make -j\\$(nproc)\n\
  cd /src/rdkit && ./Scripts/test.sh /src/rdkit/build\n\
  LOG_FILE=\\\"/src/rdkit/build/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "ndpi": "cd /src && tar -xvzf libpcap-1.9.1.tar.gz && cd libpcap-1.9.1 && ./configure --disable-shared && make -j\\$(nproc) && make install\n\
[ -d /src/json-c ] && cd /src/json-c && mkdir -p build && cd build && cmake -DBUILD_SHARED_LIBS=OFF .. && make install\n\
cd /src/ndpi && sh autogen.sh && ./configure && make -j && cd tests && ./do.sh",
    "imagemagick": "apt-get update && apt-get install -y perl build-essential wget tar libperl-dev && apt-get clean && apt-get install -y ghostscript libfreetype6-dev libbz2-dev libtiff5-dev libjpeg-dev libopenjp2-7-dev libx11-dev libxext-dev hp2xx ffmpeg && ./configure --with-perl && make && make install && ldconfig /usr/local/lib && make check ; cd PerlMagick && make test\n\
  echo 'Unit tests that call the target function:'\n\
  for log in \\$(find /src/imagemagick/tests -type f -name '*.log'); do\n\
    echo \\\"----------------------------------------\\\"\n\
    echo \\\"Test Name: \\$(basename \\\"\\$log\\\" .log)\\\"\n\
    echo \\\"----------------------------------------\\\"\n\
    cat \\\"\\$log\\\"\n\
    echo \\\"\\n\\\"\n\
  done\n\
  for log in \\$(find /src/imagemagick/Magick++ -type f -name '*.log'); do\n\
    echo \\\"----------------------------------------\\\"\n\
    echo \\\"Test Name: \\$(basename \\\"\\$log\\\" .log)\\\"\n\
    echo \\\"----------------------------------------\\\"\n\
    cat \\\"\\$log\\\"\n\
    echo \\\"\\n\\\"\n\
  done",
    "hunspell": "vulpatch compile && make check",
    "libxml2": "vulpatch compile && ASAN_OPTIONS=\'detect_leaks=0\' make check",
    "gpac": "vulpatch compile && \
        apt-get update && \
        apt-get -y install time file jackd psmisc bsdmainutils && \
        PATH=\\$PATH:/src/gpac/bin/gcc/ && \
        cd /src/testsuite && \
        ./make_tests.sh -v",
    "matio": "vulpatch compile && make CHECK_ENVIRONMENT=' 1-2800 2990-' check",
    "htslib": "autoconf && \
        autoheader && \
        ./configure && \
        make && \
        make -i check",
    "mruby": "cd /src/mruby && rake all && rake test -v",

    "libarchive": "vulpatch compile && cd /src/libarchive/build2 && ctest\n\
  LOG_FILE=\\\"/src/libarchive/build2/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",

    "libdwarf": "mkdir build && cd build && cmake ../ -DDO_TESTING=ON && make && ctest\n\
  LOG_FILE=\\\"/src/libdwarf/build/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "libsndfile": "vulpatch compile && make check",
    "file": "autoreconf -i && ./configure && make && make check",
    "assimp": "cmake CMakeLists.txt -G \"Ninja\" -DBUILD_SHARED_LIBS=OFF -DASSIMP_BUILD_ZLIB=ON -DASSIMP_BUILD_TESTS=ON -DASSIMP_BUILD_ASSIMP_TOOLS=OFF -DASSIMP_BUILD_SAMPLES=OFF && \
        cmake --build . && \
        ./bin/unit",
    "pcapplusplus": "vulpatch compile && cmake -S . -B build -DPCAPPP_BUILD_TESTS=ON && cmake --build build && cd build && make test\n\
  LOG_FILE=\\\"/src/PcapPlusPlus/build/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "c-blosc2": "cmake . -DBUILD_FUZZERS=OFF && make clean && make && ctest\n\
  LOG_FILE=\\\"/src/c-blosc2/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "libplist": "./autogen.sh --without-cython && make && make check",
    "libxml": "vulpatch compile && make check",
    "wolfssl": "./autogen.sh && ./configure && make && make check\n\
  LOG_FILE=\\\"/src/wolfssl/testsuite/testsuite.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "wireshark": "apt-get update && apt-get -y install qt5-default libgtk2.0-dev libpcap-dev && mkdir build && cd build && cmake -DBUILD_wireshark=OFF .. && make && make  test\n\
  LOG_FILE=\\\"/src/wireshark/build/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",
    "ffmpeg": "cd /src/ffmpeg ; export CFLAGS=\\\"\\$(echo \\\"\\$CFLAGS\\\" | sed 's/-gline-tables-only//')\\\" ; export CXXFLAGS=\\\"\\$(echo \\\"\\$CXXFLAGS\\\" | sed -e 's/-gline-tables-only//' -e 's/-stdlib=libc++//')\\\" ; CC=gcc CXX=g++ ./configure --samples=fate-suite/ ; make ; make fate-rsync ; make -k fate",
    "fluent-bit": "vulpatch compile && cd fluent-bit/build && make test; cat /src/fluent-bit/build/Testing/Temporary/LastTest.log",
    "flac": "cd /src/flac ; apt-get update && apt-get install -y libtool-bin libogg-dev vorbis-tools oggz-tools && ./autogen.sh && CFLAGS=\"-pthread\" LDFLAGS=\"-pthread\" ./configure && make && make check -i",  # 47525
    "harfbuzz": "apt-get update && apt-get install -y libfreetype6-dev libglib2.0-dev libcairo2-dev autoconf automake libtool pkg-config ragel gtk-doc-tools && ./autogen.sh && CFLAGS=\"-pthread\" LDFLAGS=\"-pthread\" ./configure && make && make check",
    "libredwg": "cd /src/libredwg && chmod 777 ./autogen.sh && ./autogen.sh && ./configure && make  && yes | ./unit_testing_all.sh",
    "lcms": "./autogen.sh && make && make check",
    "php-src": "vulpatch compile && make test",
    "wolfmqtt": "vulpatch compile && cd /src/wolfmqtt && bash commit-tests.sh",
    "libexif": "autoreconf -fiv && \
        ./configure && \
        make \
        && \
        make install && \
        make check",
    "zstd": "make check ",


    "leptonica": "apt update\n\
  apt install -y build-essential cmake autoconf automake libtool pkg-config zlib1g-dev libpng-dev libjpeg-dev libtiff-dev\n\
  mkdir build && cd build\n\
  cmake .. -DBUILD_PROG=1 -DCMAKE_BUILD_TYPE=Debug -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=\\\"\\$(pwd)/../prog\\\"\n\
  make -j\\\"\\$(nproc)\\\"\n\
  cd /src/leptonica\n\
  cp -v build/bin/* prog/\n\
  cd prog\n\
  export LD_LIBRARY_PATH=\\\"\\$(dirname \\\"\\$(find ../build -type f -name 'libleptonica*.so*' -print -quit)\\\"):\\$LD_LIBRARY_PATH\\\"\n\
  ./alltests_reg generate\n\
  ./alltests_reg compare 2>&1",

    "ots": "vulpatch compile && \
        cd /work/build && \
        meson test cff_charstring layout_common_table test_bad_fonts",  # do not check the fuzzing fonts
    "open62541": "apt-get install -y git build-essential gcc pkg-config cmake python cmake-curses-gui libmbedtls-dev check libsubunit-dev python-sphinx graphviz  python-sphinx-rtd-theme && mkdir build && cd build && cmake .. -DUA_BUILD_UNIT_TESTS=ON && make && make test; cat ./Testing/Temporary/LastTest.log",
    "libass": "vulpatch compile && cd /work/build && ninja test",
    "libzmq": "./autogen.sh && ./configure && make && make check",
    "lldpd": "./autogen.sh && ./configure && make && make check",
    "libxslt": "vulpatch compile && make check",

    "oniguruma": "./autogen.sh && ./configure && make && make check\n\
  find . -type f -name '*.log' ! -path \\\"./test/test-suite.log\\\" | while read -r logfile; do\n\
    echo \\\"----------------------------------------\\\"\n\
    echo \\\"FILE \\$logfile\\\"\n\
    echo \\\"----------------------------------------\\\"\n\
    cat \\\"\\$logfile\\\"\n\
    echo \\\"\\n\\\"\n\
  done",

    "libpsl": "./autogen.sh && ./configure && make && make check",

    # "sleuthkit":"apt-get update && apt-get -y install wget libcppunit-dev && ./bootstrap && ./configure && make && make check; cat ./tests/test-suite.log",
    "sleuthkit": "apt-get update && apt-get -y install wget libcppunit-dev build-essential autotools-dev automake libtool pkg-config libssl-dev zlib1g-dev && ./bootstrap && ./configure --enable-static --disable-shared CXXFLAGS=\\\"-g -O0\\\" CFLAGS=\\\"-g -O0\\\" && make \n\
    cd /root && mkdir from_brian && cd from_brian \n\
    wget -O 12-carve-ext2.zip \\\"https://downloads.sourceforge.net/project/dftt/Test%20Images/12_%20Basic%20Data%20Carving%20%232/12-carve-ext2.zip\\\" \n\
    unzip -o 12-carve-ext2.zip -d ./ \n\
    mv 12-carve-ext2/*ext2*.dd ext2fs.dd \n\
    wget -O 11-carve-fat.zip \\\"https://downloads.sourceforge.net/project/dftt/Test%20Images/11_%20Basic%20Data%20Carving%20%231/11-carve-fat.zip\\\" \n\
    unzip -o 11-carve-fat.zip -d ./ \n\
    mv 11-carve-fat/*fat*.dd fat32.dd \n\
    wget -O 3-kwsrch-ntfs.zip \\\"https://downloads.sourceforge.net/project/dftt/Test%20Images/3_%20NTFS%20Keyword%20%231/3-kwsrch-ntfs.zip\\\"  \n\
    unzip -o 3-kwsrch-ntfs.zip -d ./  \n\
    mv 3-kwsrch-ntfs/*ntfs*.dd ntfs-img-kw-1.dd  \n\
    wget -O 10b-ntfs-autodetect.zip \\\"https://downloads.sourceforge.net/project/dftt/Test%20Images/10_%20NTFS%20Autodetect%20%231/10b-ntfs-autodetect.zip\\\"  \n\
    unzip -o 10b-ntfs-autodetect.zip -d ./  \n\
    mv 10-ntfs-autodetect/*part3*.dd misc-ufs1.dd  \n\
    wget \\\"https://github.com/sleuthkit/sleuthkit_test_data/raw/refs/heads/main/nps-2009-hfsjtest1/image.gen1.zip\\\"  \n\
    unzip -o image.gen1.zip -d ./  \n\
    mv image.gen1.dmg test_hfs.dmg  \n\
    cd /src/sleuthkit/tests && make check \n\
    cd /src/sleuthkit/unit_tests && make check \n\
  find . -type f -name '*.log' | while read -r logfile; do\n\
    echo \\\"----------------------------------------\\\"\n\
    echo \\\"FILE: \\$logfile\\\"\n\
    echo \\\"----------------------------------------\\\"\n\
    cat \\\"\\$logfile\\\"\n\
    echo \\\"\\n\\\"\n\
  done",

    "libssh2": "vulpatch compile && make check",
    "fribidi": "apt-get -y install libtool autoconf && ./autogen.sh && ./configure && make && make check",
    "espeak-ng": "./autogen.sh ; ./configure ; make ; make check -k",
    "coturn": "./configure && make && make check",
    "hiredis": "apt-get update && apt-get -y install redis-server && make && make check",
    "jbig2dec": "ln -s /usr/bin/python3 /usr/bin/python && ./autogen.sh && ./configure && make && make check",
    "ntopng": "apt-get update && apt-get -y install ./autogen.sh && ",
    "jsoncpp": "vulpatch compile",

    "uwebsockets": "apt-get update \
  && apt-get install -y --no-install-recommends software-properties-common gnupg ca-certificates make pkg-config libssl-dev zlib1g-dev \
  && add-apt-repository -y ppa:ubuntu-toolchain-r/test \
  && apt-get install -y g++-9 \
  && CFLAGS=\\\"\\$(printf %s \\\"\\$CFLAGS\\\" | sed 's/-gline-tables-only//g')\\\" \
  && CXXFLAGS=\\\"\\$(printf %s \\\"\\$CXXFLAGS\\\" | sed -e 's/-gline-tables-only//g' -e 's/-stdlib=libc++//g')\\\" \
  && export CFLAGS CXXFLAGS \
  && cd /src/uWebSockets/tests \
  && make CXX=g++-9",

    # "binutils-gdb": "cd /src/binutils-gdb ; apt-get install -y dejagnu ; export CFLAGS=\\\"\\$(echo \\$CFLAGS | sed 's/-gline-tables-only//')\\\" ; export CXXFLAGS=\\\"\\$(echo \\$CXXFLAGS | sed 's/-gline-tables-only//')\\\" ; export CXXFLAGS=\\\"\\$(echo \\$CXXFLAGS | sed 's/-stdlib=libc++//')\\\" ; CC=gcc CXX=g++ ./configure ; make ; make install ; make check RUNTESTFLAGS='GDB=/usr/local/bin/gdb gdb.base/a2-run.exp'",

    "librawspeed": "mkdir build && cd build && cmake -DWITH_PTHREADS=OFF -DWITH_OPENMP=OFF -DWITH_PUGIXML=OFF -DUSE_XMLLINT=OFF -DWITH_JPEG=OFF -DWITH_ZLIB=OFF -DALLOW_DOWNLOADING_GOOGLETEST=ON .. ; make ; make test\n\
  LOG_FILE=\\\"/src/librawspeed/build/Testing/Temporary/LastTest.log\\\"\n\
  if [ -f \\\"\\$LOG_FILE\\\" ]; then\n\
    echo \\\"\\n========== Test Log Output ==========\\\"\n\
    cat \\\"\\$LOG_FILE\\\"\n\
    echo \\\"\\n========== End of Test Log ==========\\\"\n\
  else\n\
    echo \\\"\\n[ERROR] Test log file not found: \\$LOG_FILE\\\"\n\
  fi\n",

    "openthread": "apt-get update\n\
  apt-get install -y --no-install-recommends build-essential git cmake ninja-build python3 perl ca-certificates\n\
  sed -i 's/sudo //g' ./script/bootstrap\n\
  rm -rf build/simulation\n\
  CC=clang CXX=clang++ ./script/cmake-build simulation -DOT_COVERAGE=OFF -DCMAKE_C_FLAGS=\\\"-pthread\\\" -DCMAKE_CXX_FLAGS=\\\"-stdlib=libc++ -pthread\\\" -DCMAKE_EXE_LINKER_FLAGS=\\\"-pthread -lc++abi\\\"\n\
  cd build/simulation && ctest -j8 -V",

    "knot-dns": "apt-get update && apt-get -y install libtool autoconf automake make pkg-config liburcu-dev libgnutls28-dev libedit-dev liblmdb-dev && ./autogen.sh && ./configure && make && make -i check",
    "aom": "mkdir build ; cd build && cmake .. && make && ./test_libaom",
    "libgit2": "mkdir build && cd build && cmake -DBUILD_SHARED_LIBS=OFF -DUSE_HTTPS=OFF -DUSE_SSH=OFF -DUSE_BUNDLED_ZLIB=ON .. && make && ctest",  # 11382
    "unicorn": "apt-get update && apt-get install -y bsdmainutils wget xz-utils cmake libcmocka-dev && cd /src/unicorn && ./make.sh && make -i test",  # 10445
    "libreoffice": "apt-get update && apt-get install git build-essential zip ccache junit4 libkrb5-dev nasm graphviz python3 python3-dev qtbase5-dev libkf5coreaddons-dev libkf5i18n-dev libkf5config-dev libkf5windowsystem-dev libkf5kio-dev libqt5x11extras5-dev autoconf libcups2-dev libfontconfig1-dev gperf openjdk-17-jdk doxygen libxslt1-dev xsltproc libxml2-utils libxrandr-dev libx11-dev bison flex libgtk-3-dev libgstreamer-plugins-base1.0-dev libgstreamer1.0-dev ant ant-optional libnss3-dev libavahi-client-dev libxt-dev && ./autogen.sh",  # 8252

    "libjxl": "sed -i -E 's/reinterpret_cast<unsigned char\\*>\\(bytes\\.data\\(\\)\\)/const_cast<unsigned char*>(reinterpret_cast<const unsigned char*>(bytes.data()))/g; s/reinterpret_cast<const unsigned char\\*>\\(bytes\\.data\\(\\)\\)/const_cast<unsigned char*>(reinterpret_cast<const unsigned char*>(bytes.data()))/g' /src/libjxl/lib/extras/codec_jpg.cc || true && apt update && apt install -y cmake pkg-config libbrotli-dev && apt install -y libgif-dev libjpeg-dev libopenexr-dev libpng-dev libwebp-dev && cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DHWY_ENABLE_EXAMPLES=ON -DHWY_ENABLE_TESTS=OFF -DCMAKE_CXX_FLAGS=\\\"-pthread\\\" -DCMAKE_EXE_LINKER_FLAGS=\\\"-pthread\\\" -DCMAKE_SHARED_LINKER_FLAGS=\\\"-pthread\\\" && cmake --build build -- -j\\\"\\$(nproc)\\\" VERBOSE=1 && ./ci.sh test -V -j8",


    "libvips": "./autogen.sh && ./configure && make && make install && make check\n\
  find test -name \\\"*.log\\\" -type f ! -path \\\"test/test-suite.log\\\" | while read -r logfile; do\n\
    echo \\\"----------------------------------------\\\"\n\
    echo \\\"FILE: \\$logfile\\\"\n\
    echo \\\"----------------------------------------\\\"\n\
    cat \\\"\\$logfile\\\"\n\
    echo \\\"\\n\\\"\n\
  done",

    "spice-usbredir": "vulpatch compile && cd build && meson test",
    "wpantund": "vulpatch compile && make check",
    "flatbuffers": "cd /src/flatbuffers && cmake -G 'Unix Makefiles' -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS='-pthread' && make  && make test   ",
    "skia": "apt-get update && apt-get install -y software-properties-common && add-apt-repository -y ppa:ubuntu-toolchain-r/test && apt-get update && apt-get install -y gcc-9 g++-9 && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 90 && update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-9 90 && apt-get update && apt-get install -y libfontconfig1-dev && python tools/git-sync-deps && apt-get install -y clang && rm -rf out/Debug && CC=clang CXX=clang++ bin/gn gen out/Debug --args='cc=\\\"clang\\\" cxx=\\\"clang++\\\"' && ninja -C out/Debug dm && stdbuf -oL -eL out/Debug/dm -v --src tests --threads 1 2>&1",

    "lwan": "apt-get update && apt-get -y install git cmake zlib1g-dev pkg-config python-dev lua5.1-dev libsqlite3-dev libmbedtls-dev python curl && curl https://bootstrap.pypa.io/pip/2.7/get-pip.py --output get-pip.py && python get-pip.py && mkdir build && cd build && cmake .. && make && make testrunner",

    "selinux": "apt-get update && apt-get -y install libsepol-dev libcunit1-dev && vulpatch compile && make clean distclean && make DESTDIR=/src/obj install && DESTDIR=/src/obj ./scripts/env_use_destdir make test",

    "openvswitch": "vulpatch compile && make check",
    "exiv2": "vulpatch compile && cd build && ctest ../unitTests/ -E bugfixTests; cat /src/exiv2/build/Testing/Temporary/LastTest.log",
    "opensc": "apt update && apt install -y softhsm2 libglib2.0-dev\n\
  git clone https://github.com/clibs/cmocka.git /root/cmocka && \\\n\
    cd /root/cmocka && \\\n\
    cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr/local -DCMAKE_BUILD_TYPE=Debug -DUNIT_TESTING=ON && \\\n\
    cd build && make && make install\n\
  cd /src/opensc && \\\n\
    ./bootstrap && \\\n\
    sed -i '/#include <setjmp.h>/a #include <stdint.h>' configure.ac && \\\n\
    autoreconf -i && \\\n\
    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure --disable-optimization --disable-pcsc --enable-ctapi --enable-cmocka --enable-tests CFLAGS=\\\"-I/usr/local/include\\\" LDFLAGS=\\\"-L/usr/local/lib\\\" && \\\n\
    grep -rl '#include <cmocka.h>' /src/opensc | while read -r file; do\n\
      if ! grep -q '#include <stdarg.h>' \\\"\\$file\\\"; then\n\
        sed -i '/#include <cmocka.h>/i #include <stdarg.h>' \\\"\\$file\\\"\n\
      fi\n\
      if ! grep -q '#include <stddef.h>' \\\"\\$file\\\"; then\n\
        sed -i '/#include <cmocka.h>/i #include <stddef.h>' \\\"\\$file\\\"\n\
      fi\n\
      if ! grep -q '#include <stdint.h>' \\\"\\$file\\\"; then\n\
        sed -i '/#include <cmocka.h>/i #include <stdint.h>' \\\"\\$file\\\"\n\
      fi\n\
      if ! grep -q '#include <setjmp.h>' \\\"\\$file\\\"; then\n\
        sed -i '/#include <cmocka.h>/i #include <setjmp.h>' \\\"\\$file\\\"\n\
      fi\n\
    done\n\
  make -j && make install\n\
  export LD_LIBRARY_PATH=/usr/local/lib:\\$LD_LIBRARY_PATH && \\\n\
  export CMOCKA_MESSAGE_OUTPUT=stdout && \\\n\
  cd /src/opensc/src/tests && \\\n\
    make check\n\
  if [ -d /src/opensc/src/tests/unittests ]; then\n\
    find /src/opensc/src/tests/unittests -type f -executable | while read -r test_exec; do\n\
      echo \\\"Running \\$test_exec...\\\"\n\
      \\$test_exec\n\
    done\n\
  else\n\
      echo \\\"No unit tests found in this commit.\\\"\n\
  fi",

    "capstonenext": "cd /src/capstonenext\n\
	apt-get update\n\
	apt-get -y install build-essential cmake pkg-config libyaml-dev\n\
	rm -rf build\n\
	mkdir build\n\
	cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON -DCAPSTONE_BUILD_TESTS=ON -DCAPSTONE_BUILD_CSTEST=ON \n\
	cmake --build build -j\n\
  ctest --test-dir build -VV",

    "graphicsmagick": "./configure && make && make check",
}

_default_pattern = r"\n(?P<status>[A-Z]+): (?P<name>.*)"
_ctest_pattern = r"\d+/\d+\s*Test\s*#\d+:\s(?P<name>\S*)(?P<status>.+)"
_google_test_pattern = r"\[ RUN\s*\]\s(?P<name>.*)[\s\S]*?\[\s*(?P<status>.*) \]"
unittest_patterns = {
    "serenity": _ctest_pattern,
    "kimageformats": _ctest_pattern,
    "wasm3": r"\|\s+(?P<name>\S+)\s.*=>\s+(?P<status>OK|FAIL)",
    "pcre2": _default_pattern,
    "arrow": r"\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\s*\**\s*(?P<status>\S+)",
    "ndpi": r"\n(?P<name>\S+\.\S+)\s+(?P<status>OK|FAIL|ERROR|SKIPPED)",
    "yara": _default_pattern,
    "imagemagick": _default_pattern,
    "hunspell": _default_pattern,
    "opensc": _google_test_pattern,
    "openexr": _ctest_pattern,
    "libxml2": r"(?:(?:Total(?::)?\s(?:\d+\sfunctions,\s)?(?P<total>\d+)\stests,\s(?:\d+|no)\serrors)|(?:(?P<name>\S+)\s(?P<status>failed)))",
    "gpac": r"\n(?P<name>[\S]*?):.+(?P<status>(Fail|OK))",
    "matio": r"\n\s*(?P<name>\d+: .*?\S)\s+(?P<status>ok|FAILED|skipped)\b",
    # different, counts failures in groups
    "htslib": r"Testing (?P<name>.*?)\.\.\.[\s\S]*?Unexpected failures: (?P<num_unexpected_failures>\d+)\n",
    "mruby": r"(?P<name>.*?) : (?P<status>\.|F)\n",
    "libarchive": _ctest_pattern,
    "libdwarf": _ctest_pattern,
    "libsndfile": [
        r" {4}(?P<name>[\w \/]+?)\s*:\s*(?P<status>\w+)\n",
        r" {4}(?P<name>\w+)\s+:\s+\.+\s+(?P<status>\w+)\n",
        r" {4}(?P<name>[\w ]+ : \w+\.\w+)\s+(?P<status>\w+)\n",
        r" {4}(?P<name>[\w\(\) \/]+ +: .*) : (?P<status>\w+)\n",
        r" {4}(?P<name>[\w\(\) \/]+ +: .*)\s+\.+\s+(?P<status>\w+)\n",
    ],
    # passing tests have no output, so treat no status as default pass
    "file": r"Running test: (?P<name>\S+)\n.*\n(?P<status>(?i:error))?",
    "assimp": _google_test_pattern,
    "c-blosc2": _ctest_pattern,
    "rdkit": _ctest_pattern,
    "pcapplusplus": r"(?P<name>\w+)\s+: (?P<status>PASSED|FAILED)\s",
    "libplist": _default_pattern,
    "wolfssl": r"\n(?P<name>[ \w-]+)\b\s+test (?P<status>\w+)",
    "wireshark": r" *\d+\/\d+ Test +#\d+: (?P<name>\S+) \.+\*{0,3}\s{0,3}(?P<status>\w+) +",
    "ffmpeg": r"TEST\s+(?P<name>.*)(?P<status>\n(FAIL)?)",
    "fluent-bit": r"\nTest (?P<name>.+?)\.{3}[\s\S]+?\[ (?P<status>\w+) \]",
    "lcms": r"Checking (?P<name>.*) \.+(?P<status>[A-z]+)",
    "php-src": r"[\r\n](?P<status>PASS|FAIL|SKIP).*?\[(?P<name>[^\]]+)\] (?:\n|reason:)",
    # if a test fails, it won't be included at all (not even in failing), unsure what failing test looks like
    "flac": r"\+\+\+ .*?test: (?P<name>.*?)\n[^\+]*?(?P<status>PASSED)!",
    "harfbuzz": _default_pattern,
    "libredwg": r"(?P<status>ok|not ok)\s+(?P<name>\d+.*?)\n",
    "libexif": _default_pattern,
    "wolfmqtt": _default_pattern,
    "leptonica": _default_pattern,
    "zstd": r"(?:\n(?P<total>test.*)|(?P<status>[eE]rror.*)):\s+(?P<name>.*)",
    "ots": r"\d\/\d\s(?P<name>\S*)\s+(?P<status>\S*)",
    "exiv2": r"\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\s*\**\s*(?P<status>\S+)",
    "open62541": r"\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\s*\**\s*(?P<status>\S+)",
    "libass": r"\[\s*RUN\s*\]\s(?P<name>.*)[\s\S]*?(?P<status>OK|Error)",
    "libzmq": _default_pattern,
    "lldpd": _default_pattern,
    "libxslt": r"#\sRunning\s(?P<name>.*)[\s\S]*?(?:(?P<status>fail)|#|$)",
    "oniguruma": _default_pattern,
    "libpsl": _default_pattern,
    "sleuthkit": _default_pattern,
    "libssh2": _default_pattern,
    "fribidi": _default_pattern,
    "espeak-ng": r"testing\s(?P<name>.*)(?P<status>[\s\S]*?)(?=testing|make: Target 'check')",
    "coturn": r"(?P<name>.*)\s?:\s?(?P<status>.*)",
    "hiredis": r"#\d+\s(?P<name>.*): ?(?P<status>.*)",
    "jbig2dec": _default_pattern,
    "jsoncpp": r"Testing\s(?P<name>.*):\s(?P<status>.*)",
    "binutils-gdb": _default_pattern,
    "librawspeed": _ctest_pattern,
    "openthread": r" *\d+\/\d+ Test +#\d+: (?P<name>\S+) \.+\*{0,3}\s{0,3}(?P<status>\w+) +",
    "libjxl": r"\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\s*\**\s*(?P<status>\S+)",
    "libvips": _default_pattern,
    "spice-usbredir": r"\d\/\d\s(?P<name>\S*)\s+(?P<status>\S*)",
    "wpantund": _default_pattern,
    "flatbuffers": _ctest_pattern,
    "gdal": r"(?P<name>\S*)[ \t]+(?P<status>PASSED|SKIPPED|FAILED)",
    "skia": r"(?P<status>FAILURE|done)  unit test  (?P<name>[\S]*)",
    "libgit2": _ctest_pattern,
    "selinux": r"Test:\s(?P<name>\S*)\s.*\.\n?(?P<status>.+)",
    "openvswitch": r"\n\s*\d+:\s*(?P<name>.*)\s*(?P<status>ok|skipped|FAILED)",
    "aom": _google_test_pattern,
    "capstonenext": r" *\d+\/\d+ Test +#\d+: (?P<name>\S+) \.+\*{0,3}\s{0,3}(?P<status>\w+) +",
    "graphicsmagick": _default_pattern,
}
