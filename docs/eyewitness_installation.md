# Installation Instructions for EyeWitness

EyeWitness is a tool for taking screenshots of websites, providing server header information, and identifying default credentials. Follow these steps to install it manually:

## Prerequisites
- Python 3.7+
- Git
- Google Chrome (installed via Homebrew)

## Steps
1. Install Google Chrome:
   ```bash
   brew install --cask google-chrome
   ```

2. Clone the repository:
   ```bash
   git clone https://github.com/FortyNorthSecurity/EyeWitness.git
   ```

3. Navigate to the setup directory:
   ```bash
   cd EyeWitness/setup
   ```

4. Run the setup script to create a virtual environment:
   ```bash
   sudo ./setup.sh
   ```

5. Test the installation:
   ```bash
   cd ..
   source eyewitness-venv/bin/activate
   python Python/EyeWitness.py --single https://example.com
   ```

## Notes
- Ensure Python 3.7+ is installed with `venv` module support.
- If you encounter issues, refer to the [EyeWitness GitHub page](https://github.com/FortyNorthSecurity/EyeWitness) for troubleshooting.