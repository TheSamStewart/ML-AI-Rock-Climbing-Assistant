# Contribution Guide/Workflow

1. Clone the repository to your local machine using the GitHub CLI:
   ```bash
   gh repo clone TheSamStewart ML-AI-Rock-Climbing-Assistant
   ```
2. Switch to a new branch name it related to the issue you are fixing
   ```bash
   git switch -c feat/issue-1
   ```
3. Stage and commit changes
   ```bash
   git add .
   git commit -m "Add short description of changes"
   ```
4. Push branch to remote 
   ```bash
   git push -u origin my-feature-branch
   ```
5. Create the PR (this will open in web)
   ```bash
   gh pr create --title "Add new feature" --body "Description of changes made." --web
   ```