<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Notebook extends Model
{
    public $incrementing = false;

    public $timestamps = false;

    protected $keyType = 'string';

    protected $guarded = [];

    protected $hidden = ['user_id'];

    protected function casts(): array
    {
        return [
            'sort' => 'integer',
            'created_at' => 'integer',
            'updated_at' => 'integer',
            'deleted_at' => 'integer',
            'rev' => 'integer',
        ];
    }
}
