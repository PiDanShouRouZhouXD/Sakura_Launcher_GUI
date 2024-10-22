default: run

build:
  cd src/native; xmake
  cp src/native/build/windows/x64/release/native.dll ./

run: build
  python main.py

