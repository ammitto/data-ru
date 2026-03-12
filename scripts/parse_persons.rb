#!/usr/bin/env ruby
# frozen_string_literal: true

# Script to parse flattened HTML files and generate YAML
# Usage: ruby scripts/parse_persons.rb

require 'nokogiri'
require 'yaml'

def clean_text(text)
  text&.gsub(/\s+/, ' ')&.strip
end

def parse_english_file(file_path)
  doc = Nokogiri::HTML(File.read(file_path))
  result = {}

  doc.xpath('//table//tr').each do |tr|
    tds = tr.xpath('./td').to_a
    next if tds.length < 2

    name = clean_text(tds[0].text)
    title = clean_text(tds[1].text)

    next if name.nil? || name.empty?

    result[name] = { title_en: title }
  end

  result
end

def parse_russian_file(file_path)
  doc = Nokogiri::HTML(File.read(file_path))
  result = {}

  doc.xpath('//table//tr').each do |tr|
    tds = tr.xpath('./td').to_a
    next if tds.length < 3

    name_en = clean_text(tds[0].text)
    name_ru = clean_text(tds[1].text)
    title_ru = clean_text(tds[2].text)

    next if name_en.nil? || name_en.empty?

    result[name_en] = { name_ru: name_ru, title_ru: title_ru }
  end

  result
end

# Parse both files
en_data = parse_english_file('sources/announcements/20240417-en-flat.html')
ru_data = parse_russian_file('sources/announcements/20240417-ru-flat.html')

# Build entities array
entities = []
en_data.each_key do |name|
  entity = {
    'name' => {
      'ru' => ru_data[name]&.dig(:name_ru),
      'en' => name
    },
    'type' => 'individual',
    'country_code' => 'AU',
    'title' => {
      'ru' => ru_data[name]&.dig(:title_ru),
      'en' => en_data[name]&.dig(:title_en)
    },
    'effective_date' => '2024-04-17',
    'sanction_list' => 'черного списка',
    'reason' => [
      { 'ru' => 'За участие в антироссийской деятельности австралийского правительства.',
        'en' => 'For participation in anti-Russian activities of the Australian government.' }
    ],
    'measures' => [
      { 'type' => ['entry_ban'],
        'ru' => 'Запрещен въезд в Российскую Федерацию.',
        'en' => 'Entry into the Russian Federation is prohibited.' }
    ]
  }
  entities << entity
end

# Build full YAML structure
full_yaml = {
  'announcement' => {
    'title' => {
      'ru' => 'Заявление МИД России в связи с введением персональных санкций в отношении муниципальных депутатов Австралии',
      'en' => 'Foreign Ministry statement on personal sanctions on members of Australia\'s municipal councils'
    },
    'url' => 'https://mid.ru/en/foreign_policy/news/1944697/',
    'lang' => 'ru',
    'publish_date' => '2024-04-17',
    'publish_time' => '11:23',
    'authority' => 'ru/ministry-of-foreign-affairs',
    'publisher' => 'ru/ministry-of-foreign-affairs',
    'type' => 'ru/ministry-of-foreign-affairs-announcement',
    'document_id' => '703-17-04-2024',
    'signatory' => 'ru/ministry-of-foreign-affairs',
    'content' => {
      'ru' => <<~RU,
        В ответ на политически мотивированные санкции против российских физических
        и юридических лиц со стороны правительства Австралии, вводимые в рамках
        русофобской кампании «коллективного Запада», въезд в нашу страну на
        бессрочной основе закрывается дополнительно для 235 австралийцев из числа
        депутатов муниципальных собраний, формирующих в этой стране антироссийскую
        повестку дня (ниже следует поименный перечень).

        С учетом того, что официальная Канберра не намерена отказываться от
        антироссийского курса и продолжает вводить новые санкционные меры, работа
        над актуализацией российского «стоп-листа» будет продолжена.
      RU
      'en' => <<~EN
        In response to the politically motivated sanctions imposed on Russian
        private individuals and legal entities by the Government of Australia as
        part of the collective West's Russophobic campaign, the decision has been
        made to indefinitely deny entry to Russia to 235 Australian nationals who
        are members of municipal councils actively promoting the anti-Russia
        agenda in their country. The complete list of individuals affected by this
        measure follows below.

        Given that official Canberra shows no sign of renouncing its anti-Russia
        position and the continued introduction of new sanctions, we will further
        update the Russian stop list accordingly.
      EN
    }
  },
  'sanction_details' => {
    'instruments' => [
      { 'id' => 'ru/federal-law-114' }
    ],
    'entities' => entities
  }
}

# Output as YAML with header
puts '# yaml-language-server: $schema=../../schemas/announcement-schema.yml'
puts '---'
puts full_yaml.to_yaml(line_width: -1).sub(/^---\n/, '')
