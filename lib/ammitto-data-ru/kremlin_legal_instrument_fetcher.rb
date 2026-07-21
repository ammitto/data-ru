# frozen_string_literal: true

require 'mechanize'
require 'nokogiri'
require 'yaml'
require 'fileutils'
require 'date'

module AmmittoDataRU
  # Fetches and parses Russian legal instruments from the Kremlin website
  class KremlinLegalInstrumentFetcher
    BASE_URL = 'http://www.kremlin.ru/acts/bank/'.freeze

    attr_reader :agent, :output_dir, :reference_dir

    def initialize(output_dir: 'sources/legal-instruments',
                   reference_dir: 'reference-docs/legal-instruments')
      @agent = Mechanize.new do |a|
        a.user_agent_alias = 'Mac Safari'
        a.open_timeout = 30
        a.read_timeout = 60
      end
      @output_dir = output_dir
      @reference_dir = reference_dir
      FileUtils.mkdir_p(@output_dir)
      FileUtils.mkdir_p(@reference_dir)
    end

    # Download HTML from Kremlin print URL
    # @param url [String] The print URL (e.g., http://www.kremlin.ru/acts/bank/9895/print)
    # @return [String] The HTML content
    def download_html(url)
      puts "Downloading: #{url}"
      page = agent.get(url)
      page.body
    end

    # Save HTML to reference directory
    # @param html [String] HTML content
    # @param filename [String] Output filename (without extension)
    # @return [String] Path to saved file
    def save_html(html, filename)
      path = File.join(reference_dir, "#{filename}.html")
      File.write(path, html)
      puts "Saved HTML to: #{path}"
      path
    end

    # Parse HTML and extract legal instrument data
    # @param html [String] HTML content from Kremlin print page
    # @param source_url [String] The original URL the content was fetched from
    # @return [Hash] Parsed legal instrument data
    def parse_html(html, source_url: nil)
      doc = Nokogiri::HTML(html, nil, 'UTF-8')

      # Extract basic metadata
      title_element = doc.at('h1') || doc.at('title')
      full_title = title_element&.text&.strip || ''

      # Extract document ID and date from title
      doc_id = extract_document_id(full_title)
      published_date = extract_date(full_title)

      # Parse content structure
      content = parse_content(doc)

      # Get URL: prefer canonical from HTML, fallback to source_url
      url = extract_url_from_html(doc) || source_url

      {
        'id' => generate_id(doc_id),
        'title' => extract_titles(full_title),
        'url' => url,
        'type' => determine_type(full_title),
        'lang' => 'ru',
        'authority' => 'ru/state-duma',
        'publisher' => 'ru/state-duma',
        'document_id' => doc_id,
        'published_date' => published_date,
        'effective_date' => published_date,
        'content' => content
      }
    end

    # Convert parsed data to YAML format
    # @param data [Hash] Parsed legal instrument data
    # @return [String] YAML content
    def to_yaml(data)
      yaml_content = <<~YAML
        # yaml-language-server: $schema=../../schemas/cn-legal-instrument.yml
        ---
      YAML
      yaml_content + data.to_yaml(line_width: 80).sub(/^---\n/, '')
    end

    # Save YAML to output directory
    # @param yaml_content [String] YAML content
    # @param filename [String] Output filename (without extension)
    # @return [String] Path to saved file
    def save_yaml(yaml_content, filename)
      path = File.join(output_dir, "#{filename}.yml")
      File.write(path, yaml_content)
      puts "Saved YAML to: #{path}"
      path
    end

    # Main workflow: download, parse, and save
    # @param print_url [String] The Kremlin print URL
    # @param filename_base [String] Base name for output files (optional, auto-generated if not provided)
    # @return [String] Path to saved YAML file
    def fetch_and_convert(print_url, filename_base: nil)
      # Download HTML
      html = download_html(print_url)

      # Parse to extract metadata for filename if not provided
      data = parse_html(html, source_url: print_url)
      filename_base ||= generate_filename(data['document_id'], data['published_date'])

      # Save HTML reference
      save_html(html, filename_base)

      # Convert to YAML and save
      yaml_content = to_yaml(data)
      save_yaml(yaml_content, filename_base)
    end

    private

    def extract_document_id(title)
      # Match patterns like "№ 114-ФЗ" or "№ 114-ФЗ"
      match = title.match(/№\s*(\d+[-\w]*ФЗ)/i)
      return nil unless match

      "№ #{match[1]}"
    end

    def extract_date(title)
      # Match dates like "15.08.1996" or "от 15.08.1996"
      match = title.match(/(?:от\s+)?(\d{2}\.\d{2}\.\d{4})/)
      match ? format_date(match[1]) : nil
    end

    def format_date(date_str)
      # Convert DD.MM.YYYY to YYYY-MM-DD
      parts = date_str.split('.')
      "#{parts[2]}-#{parts[1]}-#{parts[0]}"
    end

    def generate_id(doc_id)
      return nil unless doc_id
      # Convert "№ 114-ФЗ" to "ru/federal-law-114"
      number = doc_id.gsub(/№\s*/, '').gsub(/-ФЗ$/, '')
      "ru/federal-law-#{number}"
    end

    def extract_titles(full_title)
      titles = []

      # Russian title (original)
      ru_title = clean_title(full_title)
      titles << { 'ru' => ru_title }

      # English translation placeholder (to be filled manually or via translation)
      titles << { 'en' => "[English translation needed] #{ru_title}" }

      titles
    end

    def clean_title(title)
      # Remove excess whitespace and normalize
      title.gsub(/\s+/, ' ').strip
    end

    def extract_url_from_html(doc)
      # Try to find canonical URL
      canonical = doc.at('link[rel="canonical"]')
      return canonical['href'] if canonical

      # Fallback to print URL base
      nil
    end

    def determine_type(title)
      if title.include?('Федеральный закон') || title.include?('ФЕДЕРАЛЬНЫЙ ЗАКОН')
        'ru/federal-law'
      elsif title.include?('Постановление')
        'ru/decree'
      elsif title.include?('Указ')
        'ru/ukaz'
      else
        'ru/legal-instrument'
      end
    end

    def generate_filename(doc_id, published_date)
      return "legal-instrument-#{Date.today.strftime('%Y%m%d')}" unless doc_id || published_date

      # Create filename like "state-duma-federal-law-114-fz-19960815"
      type_prefix = 'state-duma'
      law_type = 'federal-law'
      # Transliterate Cyrillic ФЗ to Latin fz
      number = doc_id&.gsub(/№\s*/, '')&.downcase&.gsub(/\s+/, '-')&.gsub('фз', 'fz') || 'unknown'
      date_str = published_date&.gsub('-', '') || Date.today.strftime('%Y%m%d')

      "#{type_prefix}-#{law_type}-#{number}-#{date_str}"
    end

    def parse_content(doc)
      content = []

      # Find main content area - Kremlin uses <pre id="special_pre">
      pre_content = doc.at('pre#special_pre')
      return content unless pre_content

      # Get all p and h4 elements
      elements = pre_content.search('p, h4').to_a

      # Parse preamble (text before first chapter)
      preamble = extract_preamble(elements)
      content << preamble if preamble

      # Parse chapters
      chapters = extract_chapters(elements)
      content.concat(chapters)

      content
    end

    def extract_preamble(elements)
      preamble_paragraphs = []

      elements.each do |element|
        # Normalize all whitespace including NBSP to regular space, then strip again
        text = element.text.strip.gsub(/[[:space:]]+/, ' ').strip

        # Stop at first chapter
        break if text.match?(/^Глава\s+[IVX]+\./i)

        # Skip h4 elements (headers) and empty/whitespace-only paragraphs
        next if element.name == 'h4'
        next if text.empty?

        # Skip if it looks like an article
        break if text.match?(/^Статья\s+\d+/i)

        # Skip procedural info like "Принят Государственной Думой"
        next if text.match?(/^Принят\s+Государственной/)

        # This is preamble content
        preamble_paragraphs << text
      end

      return nil if preamble_paragraphs.empty?

      {
        'type' => 'preamble',
        'content' => preamble_paragraphs.map do |t|
          { 'type' => 'paragraph', 'content' => [t] }
        end
      }
    end

    def extract_chapters(elements)
      chapters = []
      current_chapter = nil
      current_article = nil
      raw_content = []

      elements.each do |element|
        # Normalize all whitespace including NBSP to regular space, then strip again
        text = element.text.strip.gsub(/[[:space:]]+/, ' ').strip

        # Skip h4 elements (headers) and empty paragraphs
        next if element.name == 'h4'
        next if text.empty?

        # Stop at signature block (President signature at end of document)
        # Only match the actual signature line, not mentions of President in content
        if text.match?(/^Президент\s+Российской\s+Федерации\s+\p{Space}*[А-ЯA-Z]\.\p{Cyrillic}+$/)

          # Save current article before breaking
          if current_article && current_chapter
            current_article['content'] = build_article_content(current_article, raw_content)
            current_chapter['content'] << current_article
            current_article = nil
          end

          break
        end
        if text.match?(/^Москва,\s+Кремль$/)
          # Save current article before breaking
          if current_article && current_chapter
            current_article['content'] = build_article_content(current_article, raw_content)
            current_chapter['content'] << current_article
            current_article = nil
          end

          break
        end

        # Check for chapter heading
        if text.match?(/^Глава\s+[IVX]+\./i)
          # Save previous article if exists
          if current_article && current_chapter
            current_article['content'] = build_article_content(current_article, raw_content)
            current_chapter['content'] << current_article
            raw_content = []
          end

          # Save previous chapter if exists
          if current_chapter
            chapters << current_chapter
          end

          current_chapter = parse_chapter_heading(text)
          current_article = nil
        # Check for article
        elsif text.match?(/^Статья\s+\d+/i)
          # Save previous article if exists
          if current_article && current_chapter
            current_article['content'] = build_article_content(current_article, raw_content)
            current_chapter['content'] << current_article
            raw_content = []
          end

          current_article = parse_article(text)
        else
          # This is content
          if current_article
            # Add to raw content for later processing
            raw_content << text
          elsif current_chapter
            # No article but have chapter - this is chapter-level content (like "Глава исключена")
            current_chapter['content'] << { 'type' => 'paragraph', 'content' => [text] }
          end
        end
      end

      # Don't forget the last article and chapter
      if current_article && current_chapter
        current_article['content'] = build_article_content(current_article, raw_content)
        current_chapter['content'] << current_article
      end
      chapters << current_chapter if current_chapter

      chapters
    end

    # Build article content by merging initial_content with raw_content
    def build_article_content(article, raw_content)
      initial = article.delete('initial_content')
      all_lines = raw_content.dup
      all_lines.unshift(initial) if initial && !initial.strip.empty?
      parse_structured_content(all_lines)
    end

    def parse_chapter_heading(text)
      # Normalize all whitespace including NBSP
      text = text.gsub(/[[:space:]]+/, ' ')
      match = text.match(/^Глава\s+(\w+)\.?\s*(.*)$/i)
      return nil unless match

      title = match[2].to_s.strip

      {
        'type' => 'chapter',
        'index' => roman_to_arabic(match[1]).to_s,
        'label' => "Глава #{match[1]}",
        'title' => title,
        'content' => []
      }
    end

    def parse_article(text)
      # Match article numbers like "2516", "2516-1", "81", etc.
      match = text.match(/^Статья\s+(\d+(?:-\d+)?)/)
      return nil unless match

      article_num = match[1]
      # Get the remaining text after article number
      remaining_text = text.sub(/^Статья\s+#{Regexp.escape(article_num)}\.?\s*/, '').strip

      {
        'type' => 'clause',
        'index' => article_num,
        'label' => "Статья #{article_num}",
        'initial_content' => remaining_text.empty? ? nil : remaining_text
      }
    end

    # Parse raw content into structured content with lists
    def parse_structured_content(raw_lines)
      return [] if raw_lines.empty?

      result = []
      current_list = nil

      raw_lines.each do |line|
        stripped = line.strip
        # Skip empty or whitespace-only lines
        next if stripped.empty?

        # Check for numbered list item (1), 2), 10), 21), etc.)
        numbered_match = stripped.match(/^(\d+)\)\s*(.*)$/)
        if numbered_match
          if current_list.nil? || current_list['type'] != 'numbered-list'
            result << current_list if current_list
            current_list = {
              'type' => 'numbered-list',
              'content' => []
            }
          end
          current_list['content'] << {
            'type' => 'list-item',
            'label' => "#{numbered_match[1]})",
            'content' => [numbered_match[2]]
          }
          next
        end

        # Check for unnumbered list item (starting with -)
        unnumbered_match = stripped.match(/^-\s+(.*)$/)
        if unnumbered_match
          if current_list.nil? || current_list['type'] != 'unnumbered-list'
            result << current_list if current_list
            current_list = {
              'type' => 'unnumbered-list',
              'content' => []
            }
          end
          current_list['content'] << {
            'type' => 'list-item',
            'label' => '-',
            'content' => [unnumbered_match[1]]
          }
          next
        end

        # Not a list item - if we're in a list, add to the last list item's content
        # Otherwise, close the list and add as a standalone paragraph
        if current_list && !current_list['content'].empty?
          # Add to the last list item's content
          current_list['content'].last['content'] << stripped
        else
          # Close current list and add as paragraph
          if current_list
            result << current_list
            current_list = nil
          end
          result << stripped
        end
      end

      # Don't forget the last list
      result << current_list if current_list

      result
    end

    def roman_to_arabic(roman)
      roman_numerals = {
        'I' => 1, 'II' => 2, 'III' => 3, 'IV' => 4, 'V' => 5,
        'VI' => 6, 'VII' => 7, 'VIII' => 8, 'IX' => 9, 'X' => 10
      }
      roman_numerals[roman.upcase] || 0
    end
  end
end
