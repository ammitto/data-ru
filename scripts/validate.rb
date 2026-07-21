#!/usr/bin/env ruby
# frozen_string_literal: true

# CLI script to validate YAML source files against JSON Schema definitions
#
# Usage:
#   ruby scripts/validate.rb                    # Validate all files
#   ruby scripts/validate.rb --verbose          # Show all files, not just errors
#   ruby scripts/validate.rb sources/announcements/20260109.yml  # Validate specific file
#   ruby scripts/validate.rb --help             # Show help

require_relative '../lib/ammitto-data-ru'

require 'optparse'

class ValidateCLI
  def initialize
    @options = {
      verbose: false,
      files: []
    }
  end

  def run
    parse_options

    validator = AmmittoDataRU::SchemaValidator.new

    if @options[:files].any?
      # Validate specific files
      results = @options[:files].map { |f| validator.validate_file(f) }
      print_results(results)
      results.all?(&:valid)
    else
      # Validate all files
      validator.print_report(verbose: @options[:verbose])
    end
  end

  private

  def parse_options
    parser = OptionParser.new do |opts|
      opts.banner = "Usage: #{$PROGRAM_NAME} [options] [files...]"

      opts.on('-v', '--verbose', 'Show all files, not just errors') do
        @options[:verbose] = true
      end

      opts.on('-h', '--help', 'Show this help message') do
        puts opts
        exit
      end

      opts.on('--version', 'Show version') do
        puts AmmittoDataRU::VERSION
        exit
      end
    end

    parser.parse!
    @options[:files] = ARGV.dup
  end

  def print_results(results)
    valid_count = results.count(&:valid)
    invalid_count = results.count { |r| !r.valid }

    puts "\nValidation Report"
    puts "=" * 60

    results.each do |r|
      if @options[:verbose] || !r.valid
        puts r.report
      end
    end

    puts
    puts "-" * 60
    puts "Total: #{results.size} files | Valid: #{valid_count} | Invalid: #{invalid_count}"
  end
end

exit(ValidateCLI.new.run ? 0 : 1)
