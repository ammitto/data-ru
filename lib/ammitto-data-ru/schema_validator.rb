# frozen_string_literal: true

require 'yaml'
require 'json-schema'
require 'pathname'
require 'json'

module AmmittoDataRU
  # Validates YAML source files against JSON Schema definitions
  #
  # The validator maps source files to their corresponding schemas based on
  # directory location and file patterns.
  #
  # Example:
  #   validator = SchemaValidator.new
  #   results = validator.validate_all
  #   results.each { |r| puts r.report }
  #
  class SchemaValidator
    # Schema mapping configuration
    # Maps source directories/patterns to schema files
    SCHEMA_MAP = {
      'sources/announcements' => 'schemas/announcement-schema.yml',
      'sources/legal-instruments' => 'schemas/legal-instrument-schema.yml',
      'sources/supporting/document-types.yml' => 'schemas/document-types-schema.yml',
      'sources/supporting/organizations.yml' => 'schemas/organizations-schema.yml'
    }.freeze

    # Validation result for a single file
    class Result
      attr_reader :file_path, :schema_path, :errors, :valid

      def initialize(file_path:, schema_path:, errors:, valid:)
        @file_path = file_path
        @schema_path = schema_path
        @errors = errors
        @valid = valid
      end

      def report
        if valid
          "✓ #{file_path}"
        else
          lines = ["✗ #{file_path}"]
          lines += errors.map { |e| "  - #{format_error(e)}" }
          lines.join("\n")
        end
      end

      private

      def format_error(error)
        if error.is_a?(Hash)
          path = error['pointer'] || error[:path] || ''
          message = error['error'] || error[:message] || error.to_s
          "#{path}: #{message}"
        else
          error.to_s
        end
      end
    end

    attr_reader :root_dir, :schemas_dir, :sources_dir

    # Initialize validator
    # @param root_dir [String, Pathname] Project root directory (default: current directory)
    def initialize(root_dir: Dir.pwd)
      @root_dir = Pathname.new(root_dir)
      @schemas_dir = @root_dir.join('schemas')
      @sources_dir = @root_dir.join('sources')
      @schema_cache = {}
    end

    # Validate all YAML source files
    # @return [Array<Result>] Validation results for all files
    def validate_all
      results = []
      yaml_files.each do |file|
        results << validate_file(file)
      end
      results
    end

    # Validate a single file
    # @param file_path [String, Pathname] Path to YAML file (relative or absolute)
    # @return [Result] Validation result
    def validate_file(file_path)
      path = Pathname.new(file_path)
      path = root_dir.join(path) unless path.absolute?

      relative_path = path.relative_path_from(root_dir)
      schema_path = resolve_schema(relative_path)

      unless schema_path
        return Result.new(
          file_path: relative_path.to_s,
          schema_path: nil,
          errors: ['No schema mapping found for this file'],
          valid: false
        )
      end

      schema = load_schema(schema_path)
      unless schema
        return Result.new(
          file_path: relative_path.to_s,
          schema_path: schema_path,
          errors: ["Schema file not found: #{schema_path}"],
          valid: false
        )
      end

      data = load_yaml(path)
      unless data
        return Result.new(
          file_path: relative_path.to_s,
          schema_path: schema_path,
          errors: ['Failed to parse YAML file'],
          valid: false
        )
      end

      errors = validate_against_schema(data, schema)

      Result.new(
        file_path: relative_path.to_s,
        schema_path: schema_path,
        errors: errors,
        valid: errors.empty?
      )
    end

    # Get list of all YAML files in sources directory
    # @return [Array<Pathname>] List of YAML file paths
    def yaml_files
      files = []
      sources_dir.find do |path|
        next unless path.file?
        next unless path.extname == '.yml' || path.extname == '.yaml'

        files << path
      end
      files.sort
    end

    # Check if all files are valid
    # @return [Boolean] True if all files pass validation
    def all_valid?
      validate_all.all?(&:valid)
    end

    # Print validation report to stdout
    # @param verbose [Boolean] Include detailed error messages
    # @return [Boolean] True if all files are valid
    def print_report(verbose: false)
      results = validate_all

      valid_count = results.count(&:valid)
      invalid_count = results.count { |r| !r.valid }
      total_count = results.count

      puts "\nValidation Report"
      puts "=" * 60
      puts

      if verbose
        results.each { |r| puts r.report }
      else
        # Only show failures
        results.select { |r| !r.valid }.each { |r| puts r.report }
        puts "✓ #{valid_count} files valid" if valid_count > 0
      end

      puts
      puts "-" * 60
      puts "Total: #{total_count} files | Valid: #{valid_count} | Invalid: #{invalid_count}"
      puts

      invalid_count == 0
    end

    private

    # Resolve schema path for a given source file
    # @param relative_path [Pathname] Relative path from root
    # @return [String, nil] Schema path or nil if no mapping found
    def resolve_schema(relative_path)
      path_str = relative_path.to_s

      # Try exact match first (for specific files)
      return SCHEMA_MAP[path_str] if SCHEMA_MAP[path_str]

      # Try directory prefix match
      SCHEMA_MAP.each do |pattern, schema|
        next if pattern.end_with?('.yml') || pattern.end_with?('.yaml')

        if path_str.start_with?(pattern)
          return schema
        end
      end

      nil
    end

    # Load and parse a JSON Schema file
    # @param schema_path [String] Relative path to schema file
    # @return [Hash, nil] Parsed schema or nil if not found
    def load_schema(schema_path)
      return @schema_cache[schema_path] if @schema_cache.key?(schema_path)

      full_path = root_dir.join(schema_path)
      return nil unless full_path.exist?

      content = full_path.read
      schema = YAML.safe_load(content, permitted_classes: [Date, Time])

      # Remove $schema key to avoid remote resolution attempts
      # We validate against draft-07 implicitly
      schema.delete('$schema')

      # Convert schema to JSON-compatible format for json-schema gem
      @schema_cache[schema_path] = JSON.parse(schema.to_json)
    rescue StandardError => e
      warn "Error loading schema #{schema_path}: #{e.message}"
      @schema_cache[schema_path] = nil
    end

    # Load and parse a YAML file
    # @param path [Pathname] Path to YAML file
    # @return [Hash, Array, nil] Parsed YAML data or nil if error
    def load_yaml(path)
      content = path.read
      # Enable aliases for YAML anchors (e.g., &reason, *reason)
      YAML.safe_load(content, permitted_classes: [Date, Time], aliases: true)
    rescue Psych::SyntaxError => e
      warn "YAML syntax error in #{path}: #{e.message}"
      nil
    rescue StandardError => e
      warn "Error loading #{path}: #{e.message}"
      nil
    end

    # Validate data against a JSON Schema
    # @param data [Hash, Array] Data to validate
    # @param schema [Hash] JSON Schema
    # @return [Array<Hash>] Array of validation errors
    def validate_against_schema(data, schema)
      errors = []

      begin
        JSON::Validator.fully_validate(schema, data).each do |error|
          errors << parse_validation_error(error)
        end
      rescue JSON::Schema::SchemaError => e
        errors << { path: 'schema', message: "Schema error: #{e.message}" }
      rescue StandardError => e
        errors << { path: 'validation', message: "Validation error: #{e.message}" }
      end

      errors
    end

    # Parse a validation error message into structured format
    # @param error [String, Hash] Error from json-schema gem
    # @return [Hash] Structured error with path and message
    def parse_validation_error(error)
      if error.is_a?(Hash)
        {
          path: error['pointer'] || error[:path] || '',
          message: error['error'] || error[:message] || error.to_s
        }
      else
        # Parse string error format from json-schema gem
        # Format: "The property '#/foo/bar' did not match..."
        match = error.to_s.match(/The property '([^']+)' (.+)/)
        if match
          { path: match[1], message: match[2] }
        else
          { path: '', message: error.to_s }
        end
      end
    end
  end
end
