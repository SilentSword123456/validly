# Contributing to Validly

Thank you for your interest in contributing to Validly! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/yourusername/validly.git
   cd validly
   ```
3. Install dependencies:
   ```bash
   npm install
   ```
4. Set up your `.env.local` file (see `.env.example`)

## Development Workflow

1. Create a new branch for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and test them locally:
   ```bash
   npm run dev
   ```

3. Run linting before committing:
   ```bash
   npm run lint
   ```

4. Build the project to ensure there are no errors:
   ```bash
   npm run build
   ```

5. Commit your changes with a clear message:
   ```bash
   git commit -m "feat: add new feature description"
   ```

6. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

7. Open a Pull Request on GitHub

## Commit Message Convention

We follow conventional commits for clear git history:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Examples:
- `feat: add support for multiple subreddits`
- `fix: resolve timeout issue in Reddit scraper`
- `docs: update API endpoint documentation`

## Code Style

- Use TypeScript for all new code
- Follow existing code formatting (we use ESLint)
- Write clear, descriptive variable and function names
- Add comments for complex logic
- Keep functions focused and single-purpose

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix
- Update relevant documentation
- Add/update tests if applicable
- Ensure all checks pass
- Provide a clear description of changes
- Reference any related issues

## Reporting Issues

When reporting issues, please include:

- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Node version, OS, etc.)
- Relevant error messages or logs

## Questions?

Feel free to open an issue for questions or discussions about contributing.

Thank you for contributing! 🎉
