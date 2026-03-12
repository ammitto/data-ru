#!/usr/bin/env ruby
# frozen_string_literal: true

# CLI script to parse markdown announcement files to YAML format
#
# Usage:
#   ruby scripts/parse_announcements.rb                    # Parse all .md files
#   ruby scripts/parse_announcements.rb sources/announcements/20220628.md  # Parse specific file
#   ruby scripts/parse_announcements.rb --validate         # Parse and validate
#   ruby scripts/parse_announcements.rb --help             # Show help

require_relative '../lib/ammitto-data-ru'

require 'optparse'
require 'pathname'

class ParseAnnouncementsCLI
  def initialize
    @options = {
      verbose: false,
      validate: false,
      files: [],
      output_dir: nil
    }
  end

  def run
    parse_options

    parser = AmmittoDataRU::AnnouncementParser.new(verbose: @options[:verbose])

    files_to_parse = if @options[:files].any?
                       @options[:files]
                     else
                       # Find all .md files in sources/announcements
                       Pathname.new('sources/announcements').glob('*.md').sort.map(&:to_s)
                     end

    if files_to_parse.empty?
      puts "No markdown files found to parse."
      return true
    end

    puts "Parsing #{files_to_parse.length} markdown file(s)..." if @options[:verbose]

    output_files = []
    errors = []

    files_to_parse.each do |input_file|
      begin
        output_file = @options[:output_dir] ?
          File.join(@options[:output_dir], File.basename(input_file, '.md') + '.yml') :
          input_file.sub(/\.md$/, '.yml')

        parser.parse_file(input_file, output_path: output_file)
        output_files << output_file
      rescue StandardError => e
        errors << { file: input_file, error: e.message }
        puts "Error parsing #{input_file}: #{e.message}" if @options[:verbose]
      end
    end

    # Print summary
    puts
    puts "=" * 60
    puts "Parse Results"
    puts "=" * 60
    puts "Parsed: #{output_files.length} files"
    puts "Errors: #{errors.length} files"

    if errors.any?
      puts
      puts "Errors:"
      errors.each do |err|
        puts "  - #{err[:file]}: #{err[:error]}"
      end
    end

    # Validate if requested
    if @options[:validate] && output_files.any?
      puts
      puts "=" * 60
      puts "Validating parsed files..."
      puts "=" * 60

      validator = AmmittoDataRU::SchemaValidator.new
      results = output_files.map { |f| validator.validate_file(f) }

      valid_count = results.count(&:valid)
      invalid_count = results.count { |r| !r.valid }

      results.each do |r|
        puts r.report
      end

      puts
      puts "-" * 60
      puts "Validation: #{valid_count} valid | #{invalid_count} invalid"

      return errors.empty? && invalid_count == 0
    end

    errors.empty?
  end

  private

  def parse_options
    parser = OptionParser.new do |opts|
      opts.banner = "Usage: #{$PROGRAM_NAME} [options] [files...]"
      opts.separator ""
      opts.separator "Parses markdown announcement files to YAML format."
      opts.separator ""
      opts.separator "If no files are specified, parses all .md files in sources/announcements/"
      opts.separator ""
      opts.separator "Options:"

      opts.on('-v', '--verbose', 'Show verbose output') do
        @options[:verbose] = true
      end

      opts.on('--validate', 'Validate parsed files against schema') do
        @options[:validate] = true
      end

      opts.on('-o', '--output-dir DIR', 'Output directory for parsed files') do |dir|
        @options[:output_dir] = dir
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
end

exit(ParseAnnouncementsCLI.new.run ? 0 : 1)
