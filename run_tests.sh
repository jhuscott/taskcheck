#!/bin/bash

# Comprehensive test runner script for taskcheck
# Usage: ./run_tests.sh [options]

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
VERBOSE=false
COVERAGE=true
HTML_REPORT=false
SPECIFIC_TEST=""
FAIL_FAST=false
PARALLEL=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --no-coverage)
            COVERAGE=false
            shift
            ;;
        --html)
            HTML_REPORT=true
            shift
            ;;
        -t|--test)
            SPECIFIC_TEST="$2"
            shift 2
            ;;
        -x|--fail-fast)
            FAIL_FAST=true
            shift
            ;;
        -j|--parallel)
            PARALLEL=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  -v, --verbose      Run tests with verbose output"
            echo "  --no-coverage      Skip coverage reporting"
            echo "  --html             Generate HTML coverage report"
            echo "  -t, --test FILE    Run specific test file or test"
            echo "  -x, --fail-fast    Stop on first failure"
            echo "  -j, --parallel     Run tests in parallel"
            echo "  -h, --help         Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🧪 Running taskcheck tests${NC}"
echo "=================================="

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv is not installed or not in PATH${NC}"
    echo "Please install uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Install dependencies if needed
echo -e "${YELLOW}📦 Installing test dependencies...${NC}"
uv sync --extra dev

# Build pytest command
PYTEST_CMD="uv run pytest"

# Add verbose flag
if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -v"
fi

# Add coverage flags
if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=taskcheck --cov-report=term-missing"
    
    if [ "$HTML_REPORT" = true ]; then
        PYTEST_CMD="$PYTEST_CMD --cov-report=html"
    fi
fi

# Add fail fast flag
if [ "$FAIL_FAST" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -x"
fi

# Add parallel execution
if [ "$PARALLEL" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -n auto"
fi

# Add specific test if provided
if [ -n "$SPECIFIC_TEST" ]; then
    PYTEST_CMD="$PYTEST_CMD $SPECIFIC_TEST"
fi

echo -e "${BLUE}🚀 Running command: $PYTEST_CMD${NC}"
echo ""

# Run the tests
if eval $PYTEST_CMD; then
    echo ""
    echo -e "${GREEN}✅ All tests passed!${NC}"
    
    if [ "$COVERAGE" = true ] && [ "$HTML_REPORT" = true ]; then
        echo -e "${BLUE}📊 HTML coverage report generated: htmlcov/index.html${NC}"
    fi
    
    exit 0
else
    echo ""
    echo -e "${RED}❌ Tests failed!${NC}"
    exit 1
fi
