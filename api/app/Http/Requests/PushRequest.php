<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class PushRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'notebooks' => ['present', 'array'],
            'notebooks.*.id' => ['required', 'uuid'],
            'notebooks.*.name' => ['required', 'string', 'max:255'],
            'notebooks.*.sort' => ['nullable', 'integer'],
            'notebooks.*.created_at' => ['required', 'integer', 'min:0'],
            'notebooks.*.updated_at' => ['required', 'integer', 'min:0'],
            'notebooks.*.deleted_at' => ['nullable', 'integer', 'min:0'],

            'notes' => ['present', 'array'],
            'notes.*.id' => ['required', 'uuid'],
            'notes.*.notebook_id' => ['nullable', 'uuid'],
            'notes.*.title' => ['nullable', 'string', 'max:255'],
            'notes.*.blocks' => ['present', 'array'],
            'notes.*.blocks.*.type' => ['required', 'in:p,h,todo,code,link,img,hr'],
            'notes.*.tags' => ['present', 'array'],
            'notes.*.tags.*' => ['string', 'max:100'],
            'notes.*.created_at' => ['required', 'integer', 'min:0'],
            'notes.*.updated_at' => ['required', 'integer', 'min:0'],
            'notes.*.trashed_at' => ['nullable', 'integer', 'min:0'],
            'notes.*.deleted_at' => ['nullable', 'integer', 'min:0'],
        ];
    }
}
