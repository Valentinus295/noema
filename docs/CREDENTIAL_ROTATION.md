# Credential Rotation Guide

**Status:** 🔴 URGENT — A GitHub Personal Access Token (PAT) was found embedded in the `.git/config` remote URL and has been pushed to the remote repository history.

## What Happened

A GitHub PAT (`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`) was embedded in the Git remote URL:

```
url = https://ghp_XXXX@github.com/Valentinus295/noema.git
```

This means the token is:
1. **In your local `.git/config`** — *fixed now*, replaced with SSH URL.
2. **In your Git reflog** — needs cleaning.
3. **On GitHub's servers** — the token is accessible to anyone who has cloned or can view the repository history.
4. **Potentially in CI logs, clone logs, and any forks.**

## Step 1: Revoke the Exposed Token (IMMEDIATE)

1. Go to [GitHub Settings → Personal Access Tokens (Classic)](https://github.com/settings/tokens)
2. Find the token matching `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`
3. Click **Delete** / **Revoke**
4. Confirm the revocation

> **⚠️ Do this first.** A revoked token cannot be used by anyone.

## Step 2: Generate a New Token

1. Go to [GitHub Settings → Personal Access Tokens (Classic)](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Name: `noema-git-access`
4. Expiration: 90 days (recommended) or custom
5. Scopes: `repo` (minimum required for private repo access)
6. Copy the new token immediately — you won't see it again

## Step 3: Set Up Git Credential Helper (The Right Way)

**Never embed tokens in Git remote URLs.** Use a credential helper instead.

### Option A: Git Credential Manager (Recommended — Cross-Platform)

```bash
# macOS
brew install git-credential-manager

# Linux (Debian/Ubuntu)
sudo apt install git-credential-manager

# Configure
git config --global credential.helper manager

# Then on first push/pull, it will prompt for credentials
# Enter your GitHub username and paste the new PAT as the password
```

### Option B: Git Credential Store (Simpler, File-Based)

```bash
# Store credentials in plaintext file (only do this on a single-user, encrypted machine)
git config --global credential.helper store

# The next git operation will prompt for credentials and cache them
git pull
# Username: YOUR_GITHUB_USERNAME
# Password: <paste your new PAT>
```

### Option C: SSH Keys (Best Practice)

```bash
# 1. Generate an SSH key pair (if you don't have one)
ssh-keygen -t ed25519 -C "your-email@example.com" -f ~/.ssh/id_ed25519_github

# 2. Add to SSH agent
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_github

# 3. Copy the public key
cat ~/.ssh/id_ed25519_github.pub

# 4. Go to GitHub Settings → SSH and GPG Keys → New SSH Key
#    Paste the public key there

# 5. Update remote to use SSH (already done in .git/config)
#    git remote set-url origin git@github.com:Valentinus295/noema.git

# 6. Test the connection
ssh -T git@github.com
```

## Step 4: Clean Git History (If Pushed to Public/Shared Repo)

If the repository was ever public or shared:

```bash
# 1. Rotate the remote URL to SSH (done)
git remote set-url origin git@github.com:Valentinus295/noema.git

# 2. Expire the reflog and force garbage collect
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 3. Remove the token from all branches using git-filter-repo
pip install git-filter-repo
git filter-repo --replace-text <(echo "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==>REDACTED")

# 4. Force push to overwrite remote history
#    ⚠️ This rewrites history — all collaborators must re-clone
git push origin --force --all
git push origin --force --tags
```

> **Note:** Even after history rewrite, the token was valid during the window it was exposed. Revocation (Step 1) is the only reliable mitigation.

## Step 5: Prevent Future Exposure

### Add a pre-commit hook to scan for credentials

```bash
# Create the hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# Check for common credential patterns in staged files
PATTERNS=(
    'ghp_[A-Za-z0-9_]{36}'
    'gho_[A-Za-z0-9_]{36}'
    'ghu_[A-Za-z0-9_]{36}'
    'ghs_[A-Za-z0-9_]{36}'
    'ghr_[A-Za-z0-9_]{36}'
    'github_pat_[A-Za-z0-9_]{22,}'
    'sk-[A-Za-z0-9]{32,}'
    'AIza[0-9A-Za-z\-_]{35}'
)

RED='\033[0;31m'
NC='\033[0m'

for pattern in "${PATTERNS[@]}"; do
    MATCHES=$(git diff --cached -U0 | grep -E "$pattern" || true)
    if [ -n "$MATCHES" ]; then
        echo -e "${RED}🚨 CREDENTIAL DETECTED in staged changes!${NC}"
        echo "$MATCHES"
        echo ""
        echo "Commit blocked. Remove credentials and try again."
        echo "If this is a false positive, use: git commit --no-verify"
        exit 1
    fi
done

# Also check .git/config for tokens in remote URLs
if grep -qE 'https://[^@]+@github\.com' .git/config 2>/dev/null; then
    echo -e "${RED}🚨 Token found in .git/config remote URL!${NC}"
    echo "Run: git remote set-url origin git@github.com:Valentinus295/noema.git"
    exit 1
fi

exit 0
EOF

chmod +x .git/hooks/pre-commit
```

### Add .gitattributes to prevent accidental .env commits

```bash
echo ".env export-ignore" >> .gitattributes
```

## Verification Checklist

- [ ] Old token revoked on GitHub
- [ ] New token generated and stored in credential helper
- [ ] `.git/config` uses SSH or clean HTTPS (no embedded token)
- [ ] `git pull` / `git push` works with new credentials
- [ ] Pre-commit hook installed and tested
- [ ] `.env` in `.gitignore`
- [ ] No credentials in `git log -p` output

## Timeline

| Step | Action | Deadline |
|------|--------|----------|
| 1 | Revoke exposed token | **IMMEDIATELY** |
| 2 | Generate new token | Within 1 hour |
| 3 | Configure credential helper | Within 1 hour |
| 4 | Clean Git history | Within 24 hours |
| 5 | Install pre-commit hook | Within 24 hours |
