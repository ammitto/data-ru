# frozen_string_literal: true

require 'bundler/setup'
require 'ammitto-data-ru'

def fixture_path(filename)
  File.join(File.dirname(__FILE__), filename)
end
