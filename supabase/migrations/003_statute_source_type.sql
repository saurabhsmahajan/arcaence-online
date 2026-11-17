-- Allow statute documents: a source that outranks company policy.
alter table documents drop constraint if exists documents_source_type_check;
alter table documents add constraint documents_source_type_check
  check (source_type in
    ('official','superseded','email','meeting_notes','draft','spreadsheet','scan','photo','statute'));