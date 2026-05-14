#!/usr/bin/env python3
try:
    from src.app import main
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure PySide6 is installed:  pip install PySide6")
    raise

if __name__ == '__main__':
    main()
