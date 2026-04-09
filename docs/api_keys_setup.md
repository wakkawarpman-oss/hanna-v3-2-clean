# Adding API Keys for HANNA

To enable full functionality of HANNA, you need to set the following API keys in your environment:

## Required API Keys
1. **Censys**:
   - `CENSYS_API_ID`
   - `CENSYS_API_SECRET`

2. **Shodan**:
   - `SHODAN_API_KEY`

3. **Have I Been Pwned (HIBP)**:
   - `HIBP_API_KEY`

4. **Telegram**:
   - `TELEGRAM_BOT_TOKEN`

5. **GetContact**:
   - `GETCONTACT_TOKEN`
   - `GETCONTACT_AES_KEY`

## Steps to Add API Keys
1. Open your shell configuration file (e.g., `~/.zshrc` or `~/.bashrc`):
   ```bash
   nano ~/.zshrc
   ```

2. Add the API keys to the file:
   ```bash
   export CENSYS_API_ID="your_censys_api_id"
   export CENSYS_API_SECRET="your_censys_api_secret"
   export SHODAN_API_KEY="your_shodan_api_key"
   export HIBP_API_KEY="your_hibp_api_key"
   export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
   export GETCONTACT_TOKEN="your_getcontact_token"
   export GETCONTACT_AES_KEY="your_getcontact_aes_key"
   ```

3. Save the file and reload the shell configuration:
   ```bash
   source ~/.zshrc
   ```

4. Verify the keys are set:
   ```bash
   env | grep -E 'CENSYS|SHODAN|HIBP|TELEGRAM|GETCONTACT'
   ```

## Notes
- Obtain API keys from the respective services' websites.
- Ensure the keys are kept secure and not shared publicly.