#!/usr/bin/env ruby
# frozen_string_literal: true

# Script to fetch Russian legal instruments from the Kremlin website
# and convert them to the Ammitto YAML format
#
# Usage:
#   bundle exec ruby scripts/fetch_legal_instrument.rb <url> [filename_base]
#
# Example:
#   bundle exec ruby scripts/fetch_legal_instrument.rb http://www.kremlin.ru/acts/bank/9895/print

require_relative '../lib/ammitto-data-ru/kremlin_legal_instrument_fetcher'

if ARGV.empty?
  puts "Usage: #{$PROGRAM_NAME} <kremlin_print_url> [filename_base]"
  puts ""
  puts "Example:"
  puts "  #{$PROGRAM_NAME} http://www.kremlin.ru/acts/bank/9895/print"
  puts "  #{$PROGRAM_NAME} http://www.kremlin.ru/acts/bank/9895/print state-duma-federal-law-114-fz-19960815"
  exit 1
end

url = ARGV[0]
filename_base = ARGV[1]

fetcher = AmmittoDataRU::KremlinLegalInstrumentFetcher.new
fetcher.fetch_and_convert(url, filename_base: filename_base)
