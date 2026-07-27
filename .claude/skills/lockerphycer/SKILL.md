```markdown
# lockerphycer Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns and conventions used in the `lockerphycer` Python repository. You'll learn about file naming, import/export styles, commit message conventions, and how to write and run tests in this codebase. This guide is designed to help contributors quickly align with the project's established practices.

## Coding Conventions

### File Naming
- Use **camelCase** for file names.
  - **Example:** `userManager.py`, `dataHandler.py`

### Import Style
- Use **relative imports** within the repository.
  - **Example:**
    ```python
    from .utils import parseData
    ```

### Export Style
- Use **named exports** (i.e., define and export specific functions/classes).
  - **Example:**
    ```python
    def processLocker():
        pass

    class LockerManager:
        pass
    ```

### Commit Messages
- Follow **Conventional Commits**.
- Use the `feat` prefix for new features.
- Commit messages are descriptive, averaging 124 characters.
  - **Example:**
    ```
    feat: add locker assignment logic to userManager for dynamic locker allocation
    ```

## Workflows

### Feature Development
**Trigger:** When adding a new feature  
**Command:** `/feature`

1. Create a new branch for your feature.
2. Implement your feature following camelCase file naming and relative imports.
3. Add or update tests in corresponding `*.test.*` files.
4. Commit your changes using the `feat` prefix and a descriptive message.
5. Open a pull request for review.

### Testing
**Trigger:** When you need to verify code correctness  
**Command:** `/test`

1. Identify or create test files matching the `*.test.*` pattern (e.g., `lockerManager.test.py`).
2. Write tests for new or modified code.
3. Run tests using your preferred Python test runner (framework is not specified).
4. Review test results and fix any failures.

## Testing Patterns

- Test files follow the `*.test.*` naming pattern.
  - **Example:** `userManager.test.py`
- The specific testing framework is not specified; use standard Python testing tools (e.g., `unittest`, `pytest`).
- Place tests alongside or near the code they test.

  **Example test file:**
  ```python
  # userManager.test.py

  import unittest
  from .userManager import UserManager

  class TestUserManager(unittest.TestCase):
      def test_assign_locker(self):
          manager = UserManager()
          self.assertTrue(manager.assignLocker('user1'))

  if __name__ == '__main__':
      unittest.main()
  ```

## Commands
| Command    | Purpose                                      |
|------------|----------------------------------------------|
| /feature   | Start a new feature development workflow     |
| /test      | Run or write tests for the codebase          |
```