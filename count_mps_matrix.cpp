// Count constraint rows, columns, and nonzero matrix entries in an MPS file.
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

static std::vector<std::string_view> words(const std::string& line) {
  std::vector<std::string_view> result;
  const std::string_view view(line);
  for (size_t i = 0; i < view.size();) {
    while (i < view.size() && std::isspace(static_cast<unsigned char>(view[i]))) ++i;
    const size_t start = i;
    while (i < view.size() && !std::isspace(static_cast<unsigned char>(view[i]))) ++i;
    if (start != i) result.push_back(view.substr(start, i - start));
  }
  return result;
}

static bool nonzero(std::string_view value) {
  for (char c : value) {
    if (c == 'e' || c == 'E' || c == 'd' || c == 'D') break;
    if (c >= '1' && c <= '9') return true;
  }
  return false;
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  std::ifstream input(argv[1]);
  if (!input) return 2;
  std::string line, section, last_column;
  std::uint64_t rows = 0, columns = 0, nonzeros = 0;
  bool endata = false;
  std::uint64_t line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    if (line.empty() || line[0] == '*') continue;
    if (!std::isspace(static_cast<unsigned char>(line[0]))) {
      const auto tokens = words(line);
      if (!tokens.empty()) {
        section = std::string(tokens[0]);
        if (section == "ENDATA") { endata = true; break; }
      }
      continue;
    }
    if (section != "ROWS" && section != "COLUMNS") continue;
    const auto tokens = words(line);
    if (tokens.empty()) continue;
    if (section == "ROWS") {
      if (tokens.size() < 2) {
        std::cerr << "Invalid ROWS line " << line_number << ": " << line << '\n';
        return 3;
      }
      ++rows;
    } else {
      if (tokens.empty()) continue;
      if (tokens.size() >= 2 && tokens[1] == "'MARKER'") continue;
      if (tokens.size() < 3 || tokens.size() % 2 != 1) {
        std::cerr << "Invalid COLUMNS line " << line_number << ": " << line << '\n';
        return 4;
      }
      if (last_column != tokens[0]) { ++columns; last_column = tokens[0]; }
      for (size_t i = 1; i + 1 < tokens.size(); i += 2) {
        if (nonzero(tokens[i + 1])) ++nonzeros;
      }
    }
  }
  if (!endata) return 5;
  std::cout << rows << ' ' << columns << ' ' << nonzeros << '\n';
}
