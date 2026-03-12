#!/usr/bin/env ruby
# frozen_string_literal: true

# Script to flatten HTML table to 2 or 3 columns: name(s) and description
# Usage: ruby scripts/flatten_table.rb

require 'nokogiri'

def process_file(input_file, output_file, num_name_cols)
  doc = Nokogiri::HTML(File.read(input_file))

  # Find all tr elements in the table (skip header row)
  doc.xpath('//table//tr').each do |tr|
    tds = tr.xpath('./td').to_a
    next if tds.length <= num_name_cols

    # Extract text from name columns (skip first td which is number)
    name_texts = []
    (1..num_name_cols).each do |i|
      name_texts << tds[i]&.text&.strip
    end

    # Extract description from last td (combine all text, remove extra whitespace)
    desc_text = tds.last&.text&.gsub(/\s+/, ' ')&.strip || ''

    # Remove all existing tds
    tds.each(&:remove)

    # Create name tds
    name_texts.each do |name|
      name_node = Nokogiri::XML::Node.new('td', doc)
      name_node.content = name
      tr.add_child(name_node)
    end

    # Create description td
    desc_node = Nokogiri::XML::Node.new('td', doc)
    desc_node.content = desc_text
    tr.add_child(desc_node)
  end

  # Write the flattened HTML
  File.write(output_file, doc.to_html)
  puts "Flattened HTML written to #{output_file}"
end

# Process English file (2 name cols: name, description)
process_file('sources/announcements/20240417-en.html',
             'sources/announcements/20240417-en-flat.html', 1)

# Process Russian file (3 name cols: name_en, name_ru, description)
process_file('sources/announcements/20240417-ru.html',
             'sources/announcements/20240417-ru-flat.html', 2)
